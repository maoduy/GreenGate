import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Release signing: android/keystore/greengate-release.jks, passwords in keystore/README.md.
// Keep that keystore: Android refuses to update an app signed with a different key.
val ksProps = Properties().apply {
    val f = rootProject.file("keystore/keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "vn.greengate.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "vn.greengate.app"
        minSdk = 26
        // 34, not 35: Android 15 limits dataSync/specialUse foreground services for apps
        // targeting 35, and the VPN + relay link has to stay up all day.
        targetSdk = 34
        versionCode = 2
        versionName = "0.2.0"
    }

    buildFeatures { buildConfig = true }

    signingConfigs {
        create("release") {
            val ks = rootProject.file(ksProps.getProperty("storeFile") ?: "keystore/greengate-release.jks")
            if (ks.exists()) {
                storeFile = ks
                storePassword = ksProps.getProperty("storePassword")
                keyAlias = ksProps.getProperty("keyAlias")
                keyPassword = ksProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
        debug {
            applicationIdSuffix = ""
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    testOptions { unitTests.isReturnDefaultValues = true }
    packaging {
        jniLibs { useLegacyPackaging = true }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.goterl:lazysodium-android:5.1.0@aar")
    implementation("net.java.dev.jna:jna:5.13.0@aar")
    implementation("com.google.zxing:core:3.5.3")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
