plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.orienteering.gpxoverlay"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.orienteering.gpxoverlay"
        minSdk = 26
        targetSdk = 34
        versionCode = 6
        versionName = "1.5"
    }

    // Clé privée de publication, fournie par les secrets GitHub (jamais dans le dépôt).
    val releaseKeystore = System.getenv("RELEASE_KEYSTORE")?.takeIf { file(it).exists() }

    signingConfigs {
        // Clé de développement versionnée (publique) : pour les essais seulement.
        getByName("debug") {
            storeFile = file("debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
        if (releaseKeystore != null) {
            create("release") {
                storeFile = file(releaseKeystore)
                storePassword = System.getenv("RELEASE_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("RELEASE_KEY_ALIAS")
                keyPassword = System.getenv("RELEASE_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName(if (releaseKeystore != null) "release" else "debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    testOptions {
        unitTests.isIncludeAndroidResources = true
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.14.1")
}
