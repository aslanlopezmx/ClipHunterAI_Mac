CLIPHUNTER AI - INSTALACION EN MAC
==================================

Requisitos: Mac con chip Apple (M1 o posterior, o MacBook Neo) y macOS 13 o mas nuevo.
Internet solo hace falta la PRIMERA vez que se transcribe un video (descarga el modelo, ~500 MB).

1) Arrastra "ClipHunterAI" a la carpeta "Aplicaciones".

2) Abre la app desde Aplicaciones. La primera vez macOS la bloqueara porque no es de la
   App Store ("no se puede verificar..."). Es normal. Para permitirla:
     - Abre Ajustes del Sistema > Privacidad y seguridad.
     - Baja hasta ver "ClipHunterAI fue bloqueada" y pulsa "Abrir de todos modos".
     - Confirma con tu contrasena. Solo se hace una vez.

   Si dice que la app "esta danada" o no aparece la opcion anterior, abre la app Terminal
   y pega esta linea (luego intenta abrirla otra vez):
     xattr -cr /Applications/ClipHunterAI.app

3) Uso: importa un video, pulsa "Analizar video", revisa los momentos y exporta.
   - Los clips exportados quedan en:  Peliculas > ClipHunter AI > Clips
     (la app tiene un boton para abrir esa carpeta).
   - Los datos internos (base de datos, modelo, registros) estan en:
     Libreria > Application Support > ClipHunterAI

Consejos con 8 GB de RAM:
   - Cierra otras apps pesadas mientras se analiza un video largo.
   - La primera transcripcion es la mas lenta; un stream de varias horas puede tardar bastante.

Si algo falla, manda una captura del error y el archivo:
   Libreria > Application Support > ClipHunterAI > logs > app.log
