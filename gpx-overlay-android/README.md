# Trace O — trace GPX sur carte de course d'orientation (Android)

Application Android qui superpose une **trace GPX** (montre, téléphone…) sur une
**carte de course d'orientation**, fournie en **image** (JPEG, PNG, WebP…) ou en **PDF**.

## Fonctions

- Ouvrir une carte : image ou PDF (choix de la page si le PDF en contient plusieurs).
- Ouvrir une trace GPX (`trkpt`, ou `rtept` à défaut ; plusieurs segments gérés).
- Caler la trace sur la carte :
  - **Ajuster trace** : glisser pour déplacer, deux doigts pour tourner et agrandir ;
  - **Calage** par points : touchez un point de la trace, puis l'endroit
    correspondant sur la carte (un poste, un carrefour…). Avec 2 points, la trace est
    calée exactement ; avec 3 points ou plus, au mieux (moindres carrés) ;
  - **Échelle de la carte** (1:10 000, 1:15 000…) : pour un PDF, la trace est mise
    directement à la bonne taille ; pour une image, indiquez aussi sa résolution (dpi).
    Option « Verrouiller l'échelle » pour ne plus changer la taille en tournant.
- Couleur de la trace selon la vitesse (rouge = lent, vert = rapide).
- Départ (triangle) et arrivée (double cercle).
- Distance, temps et allure moyenne (min/km).
- Export de la carte avec la trace en image JPEG.
- La dernière carte, la dernière trace et le calage sont conservés à la réouverture.

## Récupérer l'APK depuis le téléphone

À chaque modification, GitHub Actions compile l'APK automatiquement :

1. Onglet **Actions** du dépôt → workflow « Android — Trace O (APK) » → dernière exécution.
2. En bas, section **Artifacts** → `TraceO-apk` (un zip qui contient `TraceO.apk`).
3. Décompressez le zip, ouvrez `TraceO.apk` et autorisez l'installation
   depuis cette source si Android le demande.

L'APK est toujours signé avec la même clé (`app/debug.keystore`) : les mises à jour
s'installent par-dessus la version précédente.

## Compiler soi-même

Avec le SDK Android installé (`ANDROID_HOME` ou `local.properties`) :

```bash
./gradlew testDebugUnitTest   # tests
./gradlew assembleRelease     # APK dans app/build/outputs/apk/release/
```

Compiler sur le téléphone avec Termux est possible mais compliqué (outils Android
pour ARM) : le plus simple est de passer par GitHub Actions.

## Structure du code

| Fichier | Rôle |
|---|---|
| `GpxParser.kt` | Lecture du GPX (SAX), dates ISO 8601 |
| `Track.kt` | Projection en mètres, distance, durée, vitesse lissée |
| `Similarity.kt` | Calcul du calage (rotation + échelle + translation) |
| `MapLoader.kt` | Chargement des images et rendu des PDF (`PdfRenderer`) |
| `OverlayView.kt` | Affichage, gestes, calage par points, export |
| `MainActivity.kt` | Menus, fichiers, réglages, sauvegarde de la session |

Aucune dépendance externe : seulement le SDK Android et Kotlin.
Android 8.0 (API 26) minimum.
