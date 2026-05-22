# Deploy en Hostinger

El sitio publico vive en `web/`. Para que Hostinger pueda desplegarlo directo
en `public_html`, GitHub Actions publica automaticamente el contenido de `web/`
en una rama separada llamada `hostinger`.

## Flujo

1. Se pushea a `main`.
2. El workflow `publish-hostinger.yml` copia `web/` a una carpeta limpia.
3. Publica esos archivos en la rama `hostinger`.
4. Hostinger despliega la rama `hostinger` en `/public_html`.

## Configuracion en Hostinger

En hPanel:

1. Entrar a Hosting -> Administrar -> Git.
2. Crear repositorio apuntando a `https://github.com/Gerguar/FUTVS.git`.
3. Seleccionar la rama `hostinger`.
4. Dejar vacia la ruta de instalacion para que use `/public_html`.
5. Activar Auto Deployment / Webhook si queres que actualice con cada push.

Notas:

- El directorio de instalacion debe estar vacio al crear el repo en Hostinger.
- Para repos privados, Hostinger pide configurar SSH/deploy key.
- La configuracion anterior de Netlify puede quedar en el repo mientras migra.
