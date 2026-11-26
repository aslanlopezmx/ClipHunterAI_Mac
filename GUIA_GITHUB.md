# Como generar el instalador de Mac (desde Ubuntu o desde el navegador)

1. En GitHub crea un repositorio nuevo (privado esta bien).
2. Sube TODO el contenido de esta carpeta, incluida la carpeta oculta `.github`
   (ahi esta la receta de compilacion). Desde Ubuntu:
       git init && git add -A && git commit -m "ClipHunter AI para Mac"
       git branch -M main
       git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
       git push -u origin main
   (Por el navegador, arrastrar archivos NO sube carpetas ocultas de forma fiable: usa git.)
3. En el repositorio: pestana **Actions** > "Compilar ClipHunter AI para Mac" > **Run workflow**.
4. Espera ~15-25 minutos. Si termina en verde, abre la ejecucion y baja
   **ClipHunterAI-mac** (seccion Artifacts, abajo). Dentro viene `ClipHunterAI-mac.dmg`.
5. Pasale el .dmg a la persona de la Mac junto con la guia (tambien va dentro del .dmg).

Si termina en rojo: abre el paso que fallo, copia el texto del error y mandamelo.
El paso "Probar la app compilada" revisa que el paquete tenga todo (FFmpeg, subtitulos,
modelo de voz, ventana), asi que la mayoria de fallos se ven aqui y no en la Mac.
