"""Training worker that runs in a separate process to avoid GIL contention."""
import logging
import multiprocessing as mp
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _training_process(
    run_id: str,
    arch_id: str,
    arch_config: Dict[str, Any],
    training_config: Dict[str, Any],
    dataset_path: Optional[str],
    checkpoint_dir: str,
    metric_queue: mp.Queue,
    stop_event: mp.Event,
    pause_event: mp.Event,
):
    """Entry point for the training subprocess."""
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset, random_split

    def emit(event: dict):
        try:
            metric_queue.put_nowait(event)
        except Exception:
            pass

    emit({"type": "status", "status": "running"})

    try:
        # ── Build model ──────────────────────────────────────────────────────
        from services.labs.architecture_registry import get_arch
        spec = get_arch(arch_id)
        if spec is None:
            raise ValueError(f"Unknown architecture: {arch_id}")
        model = spec.builder(arch_config)

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = model.to(device)

        num_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
        emit({"type": "model_info", "num_params": num_params, "device": str(device)})

        # ── Dataset ──────────────────────────────────────────────────────────
        num_classes = arch_config.get("num_classes", 10)
        if dataset_path and Path(dataset_path).exists():
            # Attempt to load a HF dataset saved as arrow files
            try:
                from datasets import load_from_disk
                hf_ds = load_from_disk(dataset_path)
                # Wrap into tensors (basic classification support)
                # This is a best-effort; real use cases need task-specific handling
                import numpy as np
                xs = torch.FloatTensor(np.array(hf_ds["train"]["pixel_values"]))
                ys = torch.LongTensor(np.array(hf_ds["train"]["label"]))
                dataset = TensorDataset(xs, ys)
            except Exception:
                dataset = _make_dummy_dataset(arch_config, num_classes, size=1000)
        else:
            dataset = _make_dummy_dataset(arch_config, num_classes, size=1000)

        val_split = training_config.get("val_split", 0.2)
        val_size = max(1, int(len(dataset) * val_split))
        train_size = len(dataset) - val_size
        train_ds, val_ds = random_split(dataset, [train_size, val_size])

        num_workers = min(training_config.get("num_workers", 2), 4)
        batch_size = training_config.get("batch_size", 16)
        train_loader = DataLoader(
            train_ds, batch_size=batch_size, shuffle=True,
            num_workers=num_workers, pin_memory=device.type == "cuda"
        )
        val_loader = DataLoader(
            val_ds, batch_size=batch_size * 2, shuffle=False, num_workers=num_workers
        )

        # ── Optimizer + Scheduler ─────────────────────────────────────────────
        lr = training_config.get("learning_rate", 3e-4)
        wd = training_config.get("weight_decay", 1e-4)
        optimizer_name = training_config.get("optimizer", "adamw").lower()
        epochs = training_config.get("epochs", 10)
        grad_clip = training_config.get("gradient_clip_norm", 1.0)
        grad_accum = training_config.get("gradient_accumulation_steps", 1)
        use_amp = training_config.get("use_mixed_precision", "fp16") != "no" and device.type == "cuda"

        if optimizer_name == "adamw":
            optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=wd)
        elif optimizer_name == "sgd":
            optimizer = torch.optim.SGD(model.parameters(), lr=lr, momentum=0.9, weight_decay=wd)
        elif optimizer_name == "adam":
            optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=wd)
        else:
            optimizer = torch.optim.RMSprop(model.parameters(), lr=lr, weight_decay=wd)

        sched_name = training_config.get("lr_scheduler", "cosine").lower()
        if sched_name == "cosine":
            scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
        elif sched_name == "linear":
            scheduler = torch.optim.lr_scheduler.LinearLR(optimizer, start_factor=1.0, end_factor=0.1, total_iters=epochs)
        elif sched_name == "onecycle":
            scheduler = torch.optim.lr_scheduler.OneCycleLR(
                optimizer, max_lr=lr, steps_per_epoch=len(train_loader), epochs=epochs
            )
        else:
            scheduler = None

        criterion = nn.CrossEntropyLoss()
        scaler = torch.cuda.amp.GradScaler(enabled=use_amp)
        checkpoint_dir_path = Path(checkpoint_dir)
        checkpoint_dir_path.mkdir(parents=True, exist_ok=True)

        best_val_loss = float("inf")
        best_ckpt = None

        # ── Training loop ─────────────────────────────────────────────────────
        for epoch in range(1, epochs + 1):
            if stop_event.is_set():
                break

            while pause_event.is_set():
                time.sleep(0.5)
                if stop_event.is_set():
                    break

            model.train()
            train_loss = 0.0
            correct = 0
            total = 0
            optimizer.zero_grad()

            for step, (inputs, labels) in enumerate(train_loader):
                if stop_event.is_set():
                    break
                while pause_event.is_set():
                    time.sleep(0.5)

                inputs, labels = inputs.to(device), labels.to(device)

                with torch.cuda.amp.autocast(enabled=use_amp):
                    outputs = model(inputs)
                    loss = criterion(outputs, labels) / grad_accum

                scaler.scale(loss).backward()

                if (step + 1) % grad_accum == 0:
                    if grad_clip > 0:
                        scaler.unscale_(optimizer)
                        torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
                    scaler.step(optimizer)
                    scaler.update()
                    optimizer.zero_grad()
                    if sched_name == "onecycle" and scheduler:
                        scheduler.step()

                train_loss += loss.item() * grad_accum
                preds = outputs.argmax(dim=1)
                correct += (preds == labels).sum().item()
                total += labels.size(0)

                if step % 10 == 0:
                    emit({
                        "type": "batch_metric",
                        "epoch": epoch,
                        "step": step,
                        "loss": round(train_loss / (step + 1), 4),
                        "lr": optimizer.param_groups[0]["lr"],
                    })

            train_loss /= max(len(train_loader), 1)
            train_acc = correct / max(total, 1)

            # Validation
            model.eval()
            val_loss = 0.0
            val_correct = 0
            val_total = 0
            with torch.no_grad():
                for inputs, labels in val_loader:
                    inputs, labels = inputs.to(device), labels.to(device)
                    with torch.cuda.amp.autocast(enabled=use_amp):
                        outputs = model(inputs)
                        loss = criterion(outputs, labels)
                    val_loss += loss.item()
                    val_correct += (outputs.argmax(1) == labels).sum().item()
                    val_total += labels.size(0)

            val_loss /= max(len(val_loader), 1)
            val_acc = val_correct / max(val_total, 1)

            if sched_name != "onecycle" and scheduler:
                scheduler.step()

            # Checkpoint
            ckpt_path = str(checkpoint_dir_path / f"epoch_{epoch:04d}.pt")
            torch.save({
                "epoch": epoch,
                "model_state": model.state_dict(),
                "optimizer_state": optimizer.state_dict(),
                "val_loss": val_loss,
            }, ckpt_path)

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_ckpt = ckpt_path

            emit({
                "type": "epoch_metric",
                "epoch": epoch,
                "total_epochs": epochs,
                "train_loss": round(train_loss, 4),
                "val_loss": round(val_loss, 4),
                "train_acc": round(train_acc, 4),
                "val_acc": round(val_acc, 4),
                "lr": optimizer.param_groups[0]["lr"],
            })

        emit({"type": "completed", "best_checkpoint": best_ckpt})

    except Exception as exc:
        import traceback
        emit({"type": "error", "message": str(exc), "traceback": traceback.format_exc()})


def _make_dummy_dataset(arch_config, num_classes, size=1000):
    import torch
    from torch.utils.data import TensorDataset

    arch_id = arch_config.get("_arch_id", "cnn")
    if arch_id in ("rnn", "lstm", "gru", "transformer"):
        vocab_size = arch_config.get("vocab_size", 10000)
        seq_len = arch_config.get("max_seq_len", 128)
        xs = torch.randint(0, vocab_size, (size, seq_len))
    else:
        img_size = arch_config.get("image_size", 32)
        in_ch = arch_config.get("in_channels", 3)
        xs = torch.randn(size, in_ch, img_size, img_size)

    ys = torch.randint(0, num_classes, (size,))
    return TensorDataset(xs, ys)


class TrainingManager:
    """Manages training subprocesses and their metric queues."""

    def __init__(self):
        self._processes: Dict[str, mp.Process] = {}
        self._queues: Dict[str, mp.Queue] = {}
        self._stop_events: Dict[str, mp.Event] = {}
        self._pause_events: Dict[str, mp.Event] = {}

    def start(
        self,
        run_id: str,
        arch_id: str,
        arch_config: dict,
        training_config: dict,
        dataset_path: Optional[str],
        checkpoint_dir: str,
    ) -> mp.Queue:
        q: mp.Queue = mp.Queue(maxsize=1000)
        stop_ev = mp.Event()
        pause_ev = mp.Event()

        # Inject arch_id into config for dummy data detection
        arch_config = {**arch_config, "_arch_id": arch_id}

        p = mp.Process(
            target=_training_process,
            args=(run_id, arch_id, arch_config, training_config, dataset_path,
                  checkpoint_dir, q, stop_ev, pause_ev),
            daemon=True,
        )
        p.start()

        self._processes[run_id] = p
        self._queues[run_id] = q
        self._stop_events[run_id] = stop_ev
        self._pause_events[run_id] = pause_ev

        return q

    def pause(self, run_id: str) -> bool:
        ev = self._pause_events.get(run_id)
        if ev:
            ev.set()
            return True
        return False

    def resume(self, run_id: str) -> bool:
        ev = self._pause_events.get(run_id)
        if ev:
            ev.clear()
            return True
        return False

    def stop(self, run_id: str) -> bool:
        stop_ev = self._stop_events.get(run_id)
        if stop_ev:
            stop_ev.set()
        pause_ev = self._pause_events.get(run_id)
        if pause_ev:
            pause_ev.clear()
        p = self._processes.get(run_id)
        if p and p.is_alive():
            p.join(timeout=10)
            if p.is_alive():
                p.terminate()
        return True

    def get_queue(self, run_id: str) -> Optional[mp.Queue]:
        return self._queues.get(run_id)

    def cleanup(self, run_id: str) -> None:
        self.stop(run_id)
        self._processes.pop(run_id, None)
        self._queues.pop(run_id, None)
        self._stop_events.pop(run_id, None)
        self._pause_events.pop(run_id, None)


training_manager = TrainingManager()
