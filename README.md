# TA’LIM PRO

O‘quv markazini boshqarish uchun Django platformasi. O‘zbek tilidagi responsive sayt, o‘rnatiladigan PWA va Android WebView ilovasi.

## Loyihani ishga tushirish

Asosiy Django kodi [`talim_pro/`](talim_pro/) ichida. Windows uchun to‘liq o‘rnatish, demo akkauntlar, Docker orqali ishga tushirish va serverga joylashtirish ko‘rsatmalari [`talim_pro/README.md`](talim_pro/README.md) faylida.

## Android APK

Android Studio loyihasi [`talim_pro/android/`](talim_pro/android/) ichida. APK yig‘ishdan oldin `android/gradle.properties` dagi `siteUrl` ni serverdagi HTTPS domen bilan almashtiring. Batafsil qadamlar [`talim_pro/android/README.md`](talim_pro/android/README.md) faylida.

APK o‘z ichida Django serverini olib yurmaydi: u onlayn joylashtirilgan saytga ulanadi. Shu sabab APK tarqatishdan oldin hosting va domenni ishga tushirish kerak.
