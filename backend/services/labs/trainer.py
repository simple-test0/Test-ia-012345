"""Training worker that runs in a separate process to avoid GIL contention."""
import logging
import multiprocessing as mp
import time
from multiprocessing.synchronize import Event as MpEvent
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _training_process(
    run_id: str,
    arch_id: str,
    arch_config: Dict[str, Any],
    training_config: Dict[str, Any],
    dataset_path: Optional[str],
    tokenizer_path: Optional[str],
    checkpoint_dir: str,
    metric_queue: mp.Queue,
    stop_event: MpEvent,
    pause_event: MpEvent,
):
    """Entry point for the training subprocess."""
    import random

    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, random_split

    def emit(event: dict):
        try:
            metric_queue.put_nowait(event)
        except Exception:
            pass

    emit({"type": "status", "status": "running"})

    try:
        # ── Reproducibility ──────────────────────────────────────────────────
        seed = training_config.get("seed", 42)
        if seed is not None:
            random.seed(seed)
            torch.manual_seed(seed)
            try:
                import numpy as np
                np.random.seed(seed)
            except ImportError:
                pass

        # ── Build model ──────────────────────────────────────────────────────
        from services.labs.architecture_registry import build_model, get_arch
        if get_arch(arch_id) is None:
            raise ValueError(f"Unknown architecture: {arch_id}")
        model = build_model(arch_id, arch_config)

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = model.to(device)

        num_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
        emit({"type": "model_info", "num_params": num_params, "device": str(device)})

        # ── Dataset ──────────────────────────────────────────────────────────
        num_classes = arch_config.get("num_classes", 10)
        using_dummy = False
        dummy_reason = ""
        if dataset_path and Path(dataset_path).exists():
            # Attempt to load a HF dataset saved as arrow files. Best-effort:
            # supports common image/text classification column layouts.
            try:
                from datasets import load_from_disk
                hf_ds = load_from_disk(dataset_path)
                split = hf_ds["train"] if "train" in hf_ds else hf_ds[list(hf_ds.keys())[0]]
                dataset = _tensor_dataset_from_hf(split, arch_config, tokenizer_path)
            except Exception as exc:
                using_dummy = True
                dummy_reason = f"dataset not parseable: {exc}"
                dataset = _make_dummy_dataset(arch_config, num_classes, size=1000)
        else:
            using_dummy = True
            dummy_reason = "no dataset selected"
            dataset = _make_dummy_dataset(arch_config, num_classes, size=1000)

        if using_dummy:
            emit({
                "type": "warning",
                "using_dummy_data": True,
                "message": f"Training on randomly-generated data — metrics are not meaningful ({dummy_reason}).",
            })

        val_split = training_config.get("val_split", 0.2)
        val_size = max(1, int(len(dataset) * val_split))
        train_size = len(dataset) - val_size
        train_ds, val_ds = random_split(dataset, [train_size, val_size])

        # num_workers must stay 0 here: this code runs in a daemonic subprocess,
        # and daemonic processes cannot spawn DataLoader worker children
        # ("daemonic processes are not allowed to have children"). Datasets are
        # in-memory TensorDatasets anyway, so workers would add nothing.
        batch_size = training_config.get("batch_size", 16)
        train_loader = DataLoader(
            train_ds, batch_size=batch_size, shuffle=True,
            num_workers=0, pin_memory=device.type == "cuda"
        )
        val_loader = DataLoader(
            val_ds, batch_size=batch_size * 2, shuffle=False, num_workers=0
        )

        # ── Optimizer + Scheduler ─────────────────────────────────────────────
        lr = training_config.get("learning_rate", 3e-4)
        wd = training_config.get("weight_decay", 1e-4)
        optimizer_name = training_config.get("optimizer", "adamw").lower()
        epochs = training_config.get("epochs", 10)
        grad_clip = training_config.get("gradient_clip_norm", 1.0)
        grad_accum = training_config.get("gradient_accumulation_steps", 1)
        use_amp = training_config.get("use_mixed_precision", "fp16") != "no" and device.type == "cuda"

        momentum = training_config.get("momentum", 0.9)
        if optimizer_name == "adamw":
            optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=wd)
        elif optimizer_name == "sgd":
            optimizer = torch.optim.SGD(
                model.parameters(), lr=lr, momentum=momentum, weight_decay=wd,
                nesterov=bool(training_config.get("nesterov", False)) and momentum > 0,
            )
        elif optimizer_name == "adam":
            optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=wd)
        elif optimizer_name == "adagrad":
            optimizer = torch.optim.Adagrad(model.parameters(), lr=lr, weight_decay=wd)
        elif optimizer_name == "adamax":
            optimizer = torch.optim.Adamax(model.parameters(), lr=lr, weight_decay=wd)
        elif optimizer_name == "nadam":
            optimizer = torch.optim.NAdam(model.parameters(), lr=lr, weight_decay=wd)
        else:
            optimizer = torch.optim.RMSprop(model.parameters(), lr=lr, weight_decay=wd)

        sched_name = training_config.get("lr_scheduler", "cosine").lower()
        warmup_epochs = int(training_config.get("warmup_epochs", 0))
        if sched_name == "cosine":
            scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
        elif sched_name == "warmup_cosine":
            import math

            def _warmup_cosine(e: int) -> float:
                if e < warmup_epochs:
                    return (e + 1) / max(warmup_epochs, 1)
                progress = (e - warmup_epochs) / max(epochs - warmup_epochs, 1)
                return 0.5 * (1.0 + math.cos(math.pi * min(progress, 1.0)))

            scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, _warmup_cosine)
        elif sched_name == "linear":
            scheduler = torch.optim.lr_scheduler.LinearLR(optimizer, start_factor=1.0, end_factor=0.1, total_iters=epochs)
        elif sched_name == "onecycle":
            scheduler = torch.optim.lr_scheduler.OneCycleLR(
                optimizer, max_lr=lr, steps_per_epoch=len(train_loader), epochs=epochs
            )
        elif sched_name == "step":
            scheduler = torch.optim.lr_scheduler.StepLR(
                optimizer,
                step_size=int(training_config.get("step_size", max(epochs // 3, 1))),
                gamma=training_config.get("gamma", 0.1),
            )
        elif sched_name == "exponential":
            scheduler = torch.optim.lr_scheduler.ExponentialLR(
                optimizer, gamma=training_config.get("gamma", 0.95)
            )
        elif sched_name == "plateau":
            scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
                optimizer,
                mode="min",
                factor=training_config.get("gamma", 0.5),
                patience=int(training_config.get("plateau_patience", 2)),
            )
        else:
            scheduler = None

        criterion = nn.CrossEntropyLoss(
            label_smoothing=float(training_config.get("label_smoothing", 0.0))
        )
        scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
        checkpoint_dir_path = Path(checkpoint_dir)
        checkpoint_dir_path.mkdir(parents=True, exist_ok=True)

        best_val_loss = float("inf")
        best_ckpt = None
        es_patience = int(training_config.get("early_stopping_patience", 0))
        es_min_delta = float(training_config.get("early_stopping_min_delta", 0.0))
        epochs_without_improvement = 0
        keep_last = int(training_config.get("keep_last_checkpoints", 3))

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

                with torch.amp.autocast("cuda", enabled=use_amp):
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
                    with torch.amp.autocast("cuda", enabled=use_amp):
                        outputs = model(inputs)
                        loss = criterion(outputs, labels)
                    val_loss += loss.item()
                    val_correct += (outputs.argmax(1) == labels).sum().item()
                    val_total += labels.size(0)

            val_loss /= max(len(val_loader), 1)
            val_acc = val_correct / max(val_total, 1)

            if sched_name != "onecycle" and scheduler:
                if sched_name == "plateau":
                    scheduler.step(val_loss)
                else:
                    scheduler.step()

            # Checkpoint
            ckpt_path = str(checkpoint_dir_path / f"epoch_{epoch:04d}.pt")
            torch.save({
                "epoch": epoch,
                "model_state": model.state_dict(),
                "optimizer_state": optimizer.state_dict(),
                "val_loss": val_loss,
            }, ckpt_path)

            if val_loss < best_val_loss - es_min_delta:
                best_val_loss = val_loss
                best_ckpt = ckpt_path
                epochs_without_improvement = 0
            else:
                epochs_without_improvement += 1

            # Keep disk usage bounded: prune old checkpoints, never the best.
            if keep_last > 0:
                all_ckpts = sorted(checkpoint_dir_path.glob("epoch_*.pt"))
                for old in all_ckpts[:-keep_last]:
                    if str(old) != best_ckpt:
                        old.unlink(missing_ok=True)

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

            if es_patience > 0 and epochs_without_improvement >= es_patience:
                emit({
                    "type": "warning",
                    "message": (
                        f"Arrêt anticipé à l'epoch {epoch}: la loss de validation "
                        f"ne s'améliore plus depuis {es_patience} epochs."
                    ),
                })
                break

        emit({"type": "completed", "best_checkpoint": best_ckpt})

    except Exception as exc:
        import traceback
        emit({"type": "error", "message": str(exc), "traceback": traceback.format_exc()})


def _tensor_dataset_from_hf(split, arch_config, tokenizer_path=None):
    """Best-effort conversion of a HF dataset split to a TensorDataset.

    Supports common column names for features (pixel_values/image/img/text/
    input_ids) and labels (label/labels/target), including PIL image columns.
    Text columns use the trained tokenizer when one is attached to the run;
    otherwise a hash fallback keeps demo runs working without a tokenizer.
    """
    import numpy as np
    import torch
    from torch.utils.data import TensorDataset

    cols = set(split.column_names)
    label_col = next((c for c in ("label", "labels", "target") if c in cols), None)
    feat_col = next(
        (c for c in ("pixel_values", "image", "img", "input_ids", "text") if c in cols),
        None,
    )
    if label_col is None or feat_col is None:
        raise ValueError(
            f"could not find feature/label columns in {sorted(cols)} "
            "(expected one of pixel_values/image/img/input_ids/text + label/labels/target)"
        )

    ys = torch.LongTensor(np.array(split[label_col]))

    raw = split[feat_col]
    if feat_col in ("input_ids",):
        xs = torch.LongTensor(np.array(raw))
    elif feat_col == "text":
        seq_len = arch_config.get("max_seq_len", 128)
        if tokenizer_path and Path(tokenizer_path).exists():
            from tokenizers import Tokenizer

            tokenizer = Tokenizer.from_file(tokenizer_path)
            pad_id = tokenizer.token_to_id("[PAD]") or 0
            tokenizer.enable_truncation(max_length=seq_len)
            tokenizer.enable_padding(length=seq_len, pad_id=pad_id, pad_token="[PAD]")
            encodings = tokenizer.encode_batch([str(t) for t in raw])
            xs = torch.LongTensor([e.ids for e in encodings])
        else:
            # Hash tokens into a fixed vocab — enough to exercise text
            # architectures when no trained tokenizer is attached.
            vocab = arch_config.get("vocab_size", 10000)
            rows = []
            for t in raw:
                toks = [(hash(w) % vocab) for w in str(t).split()[:seq_len]]
                toks += [0] * (seq_len - len(toks))
                rows.append(toks)
            xs = torch.LongTensor(rows)
    else:
        # Image-like: PIL images or arrays. Normalize to float CHW tensors.
        arr = np.array([np.asarray(im, dtype=np.float32) for im in raw])
        if arr.ndim == 3:  # (N, H, W) grayscale -> add channel
            arr = arr[:, None, :, :]
        elif arr.ndim == 4 and arr.shape[-1] in (1, 3, 4):  # NHWC -> NCHW
            arr = arr.transpose(0, 3, 1, 2)
        if arr.max() > 1.5:
            arr = arr / 255.0
        xs = torch.FloatTensor(arr)

    return TensorDataset(xs, ys)


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
        self._stop_events: Dict[str, MpEvent] = {}
        self._pause_events: Dict[str, MpEvent] = {}

    def start(
        self,
        run_id: str,
        arch_id: str,
        arch_config: dict,
        training_config: dict,
        dataset_path: Optional[str],
        checkpoint_dir: str,
        tokenizer_path: Optional[str] = None,
    ) -> mp.Queue:
        q: mp.Queue = mp.Queue(maxsize=1000)
        stop_ev = mp.Event()
        pause_ev = mp.Event()

        # Inject arch_id into config for dummy data detection
        arch_config = {**arch_config, "_arch_id": arch_id}

        p = mp.Process(
            target=_training_process,
            args=(run_id, arch_id, arch_config, training_config, dataset_path,
                  tokenizer_path, checkpoint_dir, q, stop_ev, pause_ev),
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

    def is_alive(self, run_id: str) -> bool:
        p = self._processes.get(run_id)
        return bool(p and p.is_alive())

    def cleanup(self, run_id: str) -> None:
        self.stop(run_id)
        self._processes.pop(run_id, None)
        self._queues.pop(run_id, None)
        self._stop_events.pop(run_id, None)
        self._pause_events.pop(run_id, None)


training_manager = TrainingManager()
