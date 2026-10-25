# Trace O — trace GPX sur carte de course d'orientation (Android)

Application Android qui superpose une **trace GPS** (GPX, FIT ou TCX : montre, téléphone…)
sur une **carte de course d'orientation**, fournie en **image** (JPEG, PNG, WebP…) ou en **PDF**.

## Fonctions

- Ouvrir une carte : image ou PDF (choix de la page si le PDF en contient plusieurs).
- Ouvrir une trace **GPX**, **FIT** (fichier natif des montres Garmin, Coros, Suunto…) ou **TCX**.
- **Partager vers Trace O** / **Ouvrir avec Trace O** depuis une autre app (gestionnaire de
  fichiers, Garmin, mail…) : une trace ou une carte, ou les deux en même temps.
  Strava ne partage qu'un lien : exportez le GPX depuis strava.com (« … » → « Exporter au format GPX »).
- Caler la trace sur la carte :
  - **Ajuster trace** : glisser pour déplacer, deux doigts pour tourner et agrandir ;
  - **Calage** par points : touchez un point de la trace, puis l'endroit
    correspondant sur la carte (un poste, un carrefour…). Avec 2 points, la trace est
    calée exactement ; avec 3 points ou plus, au mieux (moindres carrés) ;
  - **Échelle de la carte** (1:10 000, 1:15 000…) : pour un PDF, la trace est mise
    directement à la bonne taille ; pour une image, indiquez aussi sa résolution (dpi).
    Option « Verrouiller l'échelle » pour ne plus changer la taille en tournant.
- **Postes** : touchez la carte pour placer le départ, les postes puis l'arrivée (un poste se
  déplace en le faisant glisser). Le circuit est dessiné comme sur une carte de CO.
- **Temps intermédiaires** : temps, cumul, allure et distance de chaque section, la plus lente en
  rouge et la plus rapide en vert. Touchez une section pour la voir en bleu sur la carte.
  Le passage à un poste est le point de la trace le plus proche, à moins de 30 m ;
  « ? » signale un poste où la trace n'est pas passée assez près.
- **Rejouer** la course : un point avance sur la trace (×1 à ×50), avec le temps de course et la
  section en cours ; la carte suit le coureur.
- Couleur de la trace selon la vitesse (rouge = lent, vert = rapide).
- Départ (triangle) et arrivée (double cercle).
- Distance, temps et allure moyenne (min/km).
- Export de la carte avec la trace en image JPEG.
- La dernière carte, la dernière trace et le calage sont conservés à la réouverture.

## Récupérer l'APK depuis le téléphone

À chaque modification, GitHub Actions compile l'APK et le publie dans la release
« traceo-latest ». Lien direct (dernière version) :

https://github.com/simple-test0/Test-ia-012345/releases/download/traceo-latest/TraceO.apk

Ouvrez le fichier téléchargé et autorisez l'installation depuis cette source si Android le demande.
L'APK est aussi disponible dans l'onglet **Actions** (artifact `TraceO-apk`, en zip).

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
| `TrackParser.kt` | Reconnaît le format (GPX/TCX ou FIT) |
| `GpxParser.kt` | Lecture du GPX et du TCX (SAX), dates ISO 8601 |
| `FitParser.kt` | Lecture des fichiers FIT (messages « record ») |
| `Splits.kt` | Détection des passages aux postes, temps intermédiaires |
| `Track.kt` | Projection en mètres, distance, durée, vitesse lissée, position à un instant |
| `Similarity.kt` | Calcul du calage (rotation + échelle + translation) |
| `MapLoader.kt` | Chargement des images et rendu des PDF (`PdfRenderer`) |
| `OverlayView.kt` | Affichage, gestes, calage, postes, replay, export |
| `MainActivity.kt` | Menus, fichiers reçus, temps intermédiaires, réglages, session |

Aucune dépendance externe : seulement le SDK Android et Kotlin.
Android 8.0 (API 26) minimum.
