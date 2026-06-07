# Deploy en Hostinger

El sitio publico vive en `web/`. Para que Hostinger pueda desplegarlo desde
su opcion "Node.js con Git", GitHub Actions publica automaticamente el contenido
de `web/` en una rama separada llamada `hostinger`.

## Flujo

1. Se pushea a `main`.
2. El workflow `publish-hostinger.yml` copia `web/` a una carpeta limpia.
3. Publica esos archivos en la rama `hostinger`.
4. Hostinger despliega la rama `hostinger`.

## Configuracion en Hostinger

En hPanel, si usas "App web de Node.js" / "Importar desde Git":

1. Conectar GitHub con Hostinger.
2. Elegir el repo `Gerguar/FUTVS`.
3. Seleccionar la rama `hostinger`.
4. Comando de inicio: `npm start` o `node server.js`.
5. Directorio/app root: raiz del repo (`/`) si Hostinger lo pregunta.
6. Activar Auto Deployment si queres que actualice con cada push.

Notas:

- La rama `hostinger` incluye `package.json` y `server.js` solo para que
  Hostinger la reconozca como app Node valida.
- Para repos privados, Hostinger pide configurar SSH/deploy key.
