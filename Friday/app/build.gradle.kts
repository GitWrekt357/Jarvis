import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// API key + model come from local.properties (gitignored), never from source.
val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "com.gitwrekt.friday"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.gitwrekt.friday"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"

        buildConfigField("String", "CLAUDE_API_KEY", "\"${localProps.getProperty("CLAUDE_API_KEY", "")}\"")
        buildConfigField("String", "JARVIS_HUB_URL", "\"${localProps.getProperty("JARVIS_HUB_URL", "")}\"")
        buildConfigField("String", "JARVIS_HUB_TOKEN", "\"${localProps.getProperty("JARVIS_HUB_TOKEN", "")}\"")
        buildConfigField("String", "CLAUDE_MODEL", "\"${localProps.getProperty("CLAUDE_MODEL", "claude-sonnet-5")}\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    // Barcode scanning through Google Play Services (no camera permission needed).
    implementation("com.google.android.gms:play-services-code-scanner:16.1.0")
    debugImplementation("androidx.compose.ui:ui-tooling")
}
