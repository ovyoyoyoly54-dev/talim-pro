# TA'LIM PRO Android ilovasi

Bu loyiha Android WebView ilovasi. U Django saytiga HTTPS orqali ulanadi; akkauntlar va barcha ma'lumotlar serverda qoladi.

## APK yig'ish

1. Ommaviy HTTPS sayt manzilini `gradle.properties` ichidagi `siteUrl` qiymatiga yozing. `https://example.com` faqat namuna.
2. Android Studio'da shu `android` papkasini oching va Gradle sinxronlashini tugating.
3. JDK 17 va Android SDK Platform 36 o'rnatilganini tekshiring. Loyiha Android Gradle Plugin 8.13.2 va Gradle 8.13 bilan sozlangan.
4. Android Studio menyusidan **Build → Build Bundle(s) / APK(s) → Build APK(s)** ni tanlang.
5. Sinov APK odatda `app/build/outputs/apk/debug/app-debug.apk` manzilda paydo bo'ladi. Tarqatish uchun Android Studio'dan imzolangan release APK yarating.

Ilova faqat HTTPS manzilda ishlaydi. Domen o'zgarsa, yangi APK'ni qayta yig'ish kerak. Ichki sayt havolalari WebView'da, tashqi saytlar telefon brauzerida ochiladi.
