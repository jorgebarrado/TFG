# Manual de Usuario

Este manual describe los flujos principales de CiteCheck desde la perspectiva de una persona usuaria.

## Registro e Inicio de Sesión

Puedes usar CiteCheck en modo lectura para explorar algunos contenidos, pero para interactuar con reportes necesitas iniciar sesión.

Opciones disponibles según configuración del entorno:

- usuario y contraseña;
- Google;
- ORCID.

Al iniciar sesión, la aplicación redirige a la página principal.

## Perfil

Desde el menú de usuario puedes abrir tu perfil y ajustes.

En ajustes puedes modificar:

- nombre y usuario;
- avatar y biografía;
- país, idioma preferido, profesión, institución y área de investigación;
- enlaces sociales;
- correo de contacto;
- URL de DBLP;
- preferencias de notificación;
- privacidad del perfil y visibilidad de actividad/enlaces;
- contraseña.

El idioma preferido se guarda en cookie cuando se actualiza el perfil.

## DBLP

Si añades una URL de DBLP, CiteCheck puede listar tus publicaciones y mostrar información de citas cuando las APIs externas lo permitan.

También puedes introducir una URL de DBLP manualmente desde la pantalla de artículos DBLP sin guardarla en tu perfil.

## Reportes de Citas Incorrectas

Un reporte describe que un artículo citador interpreta o usa incorrectamente otro artículo.

Campos principales:

- DOI original: trabajo citado o interpretado;
- DOI citador: trabajo donde aparece la cita problemática;
- tipo de error:
  - `Not Said`;
  - `Misinterpretation`;
  - `Contextual Misattribution`;
- área de publicación;
- explicación del problema;
- contextos extraídos, si el sistema pudo encontrarlos.

En el detalle de un reporte puedes:

- leer metadatos y explicación;
- ver contextos extraídos;
- comentar o responder comentarios;
- votar;
- guardar el reporte;
- abrir el reader si hay PDF disponible;
- editar o borrar si eres autor o superusuario.

## Comentarios, Votos y Guardados

Los comentarios permiten discutir un reporte. Las respuestas se muestran como hilos.

Los votos indican acuerdo o desacuerdo con el reporte. Cada usuario solo puede emitir un voto por reporte.

Los reportes guardados aparecen en tu área personal para consulta posterior.

## Mensajes y Notificaciones

Los perfiles públicos permiten iniciar conversaciones privadas con otros usuarios.

Las notificaciones cubren eventos como:

- comentarios nuevos;
- votos en reportes propios;
- mensajes nuevos;
- avisos del sistema.

Puedes marcar notificaciones como leídas individualmente o todas a la vez.

## Reader PDF

El reader sirve para inspeccionar PDFs y relacionar referencias con menciones.

Modos habituales:

1. **Preview/subida manual**
   - Abres `/citations/reader/preview/`.
   - Subes un PDF.
   - El sistema intenta extraer referencias, snippets, capas y DOI del artículo.
   - Puedes revisar referencias y contextos sin crear necesariamente un reporte.

2. **Reporte existente**
   - Desde un reporte, abres el reader.
   - Si el sistema encuentra un PDF open access para el DOI citador, lo carga.
   - El reader muestra menciones guardadas y referencias asociadas.

3. **Debug de referencias**
   - En entornos de desarrollo, puede activarse debug para descargar JSON diagnóstico.
   - Esta función es para mantenimiento técnico, no para usuarios finales.

## Revisión de Citadores

La zona de revisión de citas permite partir de publicaciones y buscar trabajos que las citan. Cuando hay PDFs open access, CiteCheck intenta localizar el contexto textual de la cita.

El resultado automático debe revisarse manualmente antes de crear un reporte.

## Limitaciones Para Usuarios

- Si no hay PDF open access, el sistema no podrá extraer contexto automáticamente.
- Los PDFs escaneados pueden no producir texto.
- Los metadatos externos pueden estar incompletos o tardar en responder.
- La detección automática ayuda a encontrar evidencia, pero no decide si una cita es incorrecta.
