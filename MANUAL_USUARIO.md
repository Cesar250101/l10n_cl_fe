# Manual de Usuario — Facturación Electrónica para Chile

Módulo: `l10n_cl_fe` · Odoo 16 · Localización chilena (SII)

Este manual explica, desde la perspectiva de quien usa el sistema (administrador, contador, facturación), cómo configurar y operar el módulo base de Facturación Electrónica Chilena. Cubre la emisión de documentos de venta (Factura, Nota de Crédito/Débito, exportación), la recepción de documentos de proveedores, los libros mensuales y las herramientas de mantenimiento (certificado digital, folios CAF, MEPCO).

> Si además tiene instalado `l10n_cl_dte_point_of_sale` (Boleta electrónica en el Punto de Venta) o `l10n_cl_stock_picking` (Guía de Despacho Electrónica), esos módulos tienen su propio manual — este documento cubre la base común de Facturación Electrónica.

---

## 1. ¿Qué hace este módulo?

Integra Odoo con el SII (Servicio de Impuestos Internos de Chile) para emitir y recibir Documentos Tributarios Electrónicos (DTE):

- **Emisión**: Factura Afecta/Exenta (33/34), Nota de Crédito (61)/Débito (56), Factura/NC/ND de Exportación (110/111/112), Factura de Compras (46), Liquidación de Factura (43, parcial).
- **Recepción**: descarga y procesamiento automático de XML de proveedores por correo, con flujo de aceptación/reclamo hacia el SII.
- **Libros mensuales**: Libro de Compra/Venta, Libro de Honorarios (parcial).
- **Consumo de Folios**: reporte diario de boletas para el SII (usado junto con boleta desde POS u otros orígenes).
- **Gestión de folios (CAF)**: carga manual de archivos CAF o solicitud automática vía API (apicaf.cl).
- **Firma electrónica**: almacenamiento del certificado digital de la empresa, con alertas de vencimiento.
- **MEPCO**: sincronización automática de tasas de impuesto específico a combustibles.
- **Portal público**: consulta y descarga de boletas por folio, sin necesidad de iniciar sesión.

### Requisitos previos (instalación)

Dependencias Python declaradas en `requirements.txt` del módulo:

| Paquete | Para qué se usa |
|---|---|
| `facturacion_electronica` (≥0.18.0, versión recomendada actual 0.19.0) | Librería central: genera y firma el XML del DTE. Obligatoria. |
| `num2words` | Montos en palabras en los reportes impresos. |
| `xlsxwriter` | Exportar a Excel el Libro de Compra/Venta y otros reportes. |
| `pillow` | Manejo de imágenes (timbre PDF417). |
| `PyMuPDF` (≥1.21.1) | Solo necesario si se sincroniza MEPCO leyendo el PDF del Diario Oficial. |
| `pytesseract` (≥0.3.10) | Solo necesario para el mismo caso anterior (OCR); requiere además el paquete de sistema `tesseract-ocr`. |

La versión instalada de `facturacion_electronica` se muestra en **Ajustes → sección "Facturación Electrónica"**, con una alerta roja si está desactualizada.

---

## 2. Mapa de menús

Este módulo **no crea una app propia**: todo vive dentro de los menús estándar de **Contabilidad/Facturación** de Odoo.

- **Contabilidad → Configuración → SII Configuration** (submenú nuevo) — catálogos SII, Firma Electrónica, CAF, Configuraciones DTE, Cola de envío, XML request.
- **Contabilidad → Recepcionar XML Intercambio** (submenú nuevo) — recepción de documentos de proveedores.
- **Contabilidad → Informes (Reporting)** — Consumo de Folios, Libros Cierre de Mes.
- **Ajustes → (sección) Facturación Electrónica** — configuración general del servicio DTE.
- **Ajustes → Usuarios y Compañías → Compañías** — datos tributarios de la empresa (RUT, resolución, ambiente).
- **Contabilidad → Configuración → Diarios contables** — folios y tipos de documento por diario.

---

## 3. Configuración inicial

Siga este orden la primera vez que configura el módulo.

### 3.1 Datos tributarios de la Compañía

**Ajustes → Usuarios y Compañías → Compañías**, abrir la empresa:

| Campo | Qué es |
|---|---|
| **DTE Service Provider** | Ambiente de envío: **"SII - Certification process"** (SIICERT, ambiente de pruebas, valor por defecto) o **"www.sii.cl"** (SII, producción real). **Cambie a producción solo cuando haya certificado válido y haya probado en certificación.** |
| **DTE EMail** | Alias de correo (`mail.alias`) al que los proveedores envían el XML de intercambio; Odoo lo procesa automáticamente. |
| **SII Exempt Resolution Number / Date** | Número y fecha de la Resolución SII que autoriza a facturar electrónicamente. Obligatorio en ambiente SII/SIICERT. |
| **SII Regional Office** | Dirección Regional del SII que corresponde a la empresa. |
| **Document type / Document Number** | Reemplazan el campo RUT estándar de Odoo: tipo de documento de identidad y el RUT de la empresa. |
| **Responsability** | Responsabilidad Tributaria SII de la empresa — determina qué tipos de documento puede emitir/recibir. |
| **Start-up Date** | Fecha de inicio de actividades. |
| **Giros de La Compañia** (`company_activities_ids`) y **Glosa Giro** | Actividades económicas y su descripción textual. Obligatorios en ambiente SII/SIICERT. |
| **Comuna** (`city_id`) | Comuna de la dirección de la empresa. |
| **Sucursales de la compañía** (`sucursal_ids`) | Ver 3.5. |

### 3.2 Firma Electrónica (certificado digital)

**Requiere permiso de Administrador (Ajustes)** — un usuario contable normal puede ver los certificados pero no cargarlos ni editarlos.

Acceso: **Ajustes → sección "Facturación Electrónica" → botón "Firmas Electrónica"**.

Al crear una firma nueva, el formulario arranca en estado **Unverified** y solo muestra dos campos: el archivo del certificado (`.pfx`) y su clave. Pasos:

1. Suba el archivo del certificado y escriba la clave.
2. Presione **"Validate Certificate"**. El sistema lee el certificado y completa automáticamente los datos técnicos (RUT del firmante — "Subject Serial Number", fechas de vigencia, algoritmo, etc.) y cambia el estado a **Valid** (o **Incomplete** si falta algo).
3. En la pestaña **"Authorizations"**, agregue los **usuarios** y **compañías** autorizados a firmar DTE con este certificado.

Botones adicionales: **"Descargar Certificado"** y **"Ver Clave"**.

**Alertas de vencimiento:** solo llegan como notificación emergente en pantalla a los usuarios listados en "Authorized Users" de la firma, cuando falten 30 días o menos para el vencimiento (o ya esté vencido). Si la persona responsable de renovar el certificado no está en esa lista, no verá la alerta — revise que esté agregada.

### 3.3 Archivos CAF (folios)

Un CAF autoriza un rango de folios para un tipo de documento específico y vence a los 6 meses. Acceso: **Ajustes → sección "Facturación Electrónica" → botón "Archivos CAF"**.

Carga manual:
1. Crear un registro nuevo y subir el archivo `.xml` del CAF descargado desde el sitio del SII, campo **CAF File**.
2. Presionar **"Load CAF"** — el sistema lee el archivo y completa: tipo de documento, folio inicial/final, fecha de emisión/vencimiento, RUT, y la **secuencia (`ir.sequence`)** que efectivamente numerará los documentos.
3. Una barra de progreso (**Use Level**) muestra visualmente cuántos folios quedan disponibles (azul = en uso, rojo = agotado).

Pestañas útiles: **"Mantención"** (inspeccionar/expirar folios sin usar) y **"Folios Anulados"** (consultar al SII los folios que fueron anulados).

### 3.4 Obtener Folios desde el SII (apicaf.cl) — alternativa sin descargar el CAF manualmente

Requiere configurar antes, en Ajustes: **"Url Api Emisión Folios"** y **"Token Api Emisión de Folios"** (credenciales del servicio apicaf.cl).

Se abre con el botón **"Obtener Folios desde el SII"**, disponible en varios lugares: Ajustes, la pestaña "Documents" del Diario, la línea de tipo de documento del diario, y la ficha de Secuencia.

Flujo:
1. Elegir **Operación**: **Solicitar Folios** (pedir folios nuevos), **Reobtener Folios** (re-descargar un CAF ya emitido) o **Anular Folios** (anular un rango no usado directamente ante el SII).
2. Elegir **Compañía** y **Firma Electrónica** — al seleccionarlas, el sistema se conecta automáticamente a apicaf.cl.
3. Elegir la **Secuencia**/tipo de documento.
4. Según la operación: ingresar la cantidad a solicitar, o marcar el CAF a reobtener/anular, o ingresar el rango y el motivo de anulación.
5. Confirmar con **"Obtener CAF"** o **"Anular Folios"**.

> Recordatorio que muestra el propio asistente: pida solo la cantidad de folios que pueda emitir en un plazo máximo de 6 meses, ya que después vencen y hay que anularlos manualmente en el sitio del SII. Al solicitar folios exitosamente, el sistema crea y carga el CAF automáticamente — no hace falta subir el XML a mano.

Si aparece el mensaje **"Usuario Baneado temporalmente"**, use el botón **"Remover Bloqueo (Ban)"** que aparece junto al error.

### 3.5 Sucursales SII

No tiene menú propio: se administran directamente desde la ficha de **Compañía** (campo "Sucursales de la compañía", creación rápida) o desde la ficha de un **Diario** (campo Sucursal). Cada sucursal tiene nombre, código SII y un contacto/dirección asociada. Sirve para declarar los distintos puntos de emisión de la empresa ante el SII.

### 3.6 Configurar un Diario para emitir DTE

**Contabilidad → Configuración → Diarios contables**, abrir (o crear) el diario:

1. Active **"Use Documents?"** (solo diarios de venta/compra).
2. Asigne la **Sucursal** correspondiente.
3. Vaya a la pestaña nueva **"Documents"** y presione **"Create Journal Documents"** — abre un asistente que crea de una vez todas las líneas de tipo de documento según lo que se active:
   - Para diarios de **venta**: "Register Electronic Documents?" (Factura/NC/ND electrónicas), "Register Manual Documents?" (documentos no electrónicos), "¿Incluir Boleta Electrónica?", "Register Settlement Invoices?" (Liquidación), y para documentos manuales también "Register Free-Tax Zone..." y "Unusual Documents" (traspaso/reexpedición).
   - Para diarios de **compra**: solo aparece la opción **"Emitir Factura de Compra Electrónica"** (código SII 46) — el asistente aclara expresamente: *esto NO es lo mismo que registrar facturas de proveedor normales; solo actívelo si la empresa tiene resolución para emitir Factura de Compra Electrónica.*

   Antes de poder confirmar, la Compañía debe tener configurada su **Responsabilidad Tributaria** (paso 3.1) — si falta, el asistente lo bloquea con un error explícito.

4. El asistente crea las líneas de la tabla **"Journal SII Documents"**, cada una con: tipo de documento SII, secuencia de folios (`ir.sequence`) y folios disponibles.
5. Use el botón **"Obtener Folios desde el SII"** (3.4) para cargar folios reales a cada tipo de documento recién creado.
6. Configure **"Giros del Diario"** (obligatorio una vez que hay documentos configurados) con los giros de la compañía que aplican a este diario.

### 3.7 Catálogos SII de referencia

La mayoría son catálogos que el usuario consulta pero rara vez edita (edición reservada a Contabilidad: Administrador). Todos bajo **Contabilidad → Configuración → SII Configuration**: Document Classes, Document Types, Responsibilities, Concept Types, SII Regional Offices, SII Partner Activities. No requieren mantención habitual salvo casos especiales.

### 3.8 Ficha de Contacto (cliente/proveedor)

En cualquier ficha de **Contacto**, este módulo agrega:

| Campo | Qué es |
|---|---|
| **Glosa Descriptiva (Giro)** / **Actividades del partner** | Giro comercial del contacto. |
| **Document type / Document Number** | Reemplazan el RUT estándar de Odoo. |
| **Responsability** | Responsabilidad Tributaria del contacto (define qué letras de documento puede emitir/recibir). |
| **DTE EMail** | Correo específico para el envío del DTE a este cliente (obligatorio salvo que el contacto sea "Mipyme"). |
| **Es Mipyme** | Afecta si el correo DTE es obligatorio. |
| **Opciones DTE** (en contactos hijos tipo "dte") | Casillas "Enviar DTE" y "Principal" — permite tener varios correos de contacto y marcar cuáles reciben el documento. |

### 3.9 Impuestos y MEPCO

**Contabilidad → Configuración → Impuestos**, en la ficha de un impuesto:

- **Indicador Exento por defecto** — códigos SII de exención/no venta (varias opciones para boleta/guía).
- **Base Precio Incluído Chileno** — equivalente a "incluir en base imponible" para precios con impuesto incluido.
- **Indicador Mepco** — si el impuesto es Diesel, Gasolina 93 o Gasolina 97, aparecen los botones:
  - **"Actualizar Mepco"** — sincroniza la tasa vigente desde el **"Origen actualización Mepco"** elegido: Página del SII, Página DiarioOficial.cl, PDF subido, o Manual.
  - **"Valores Mepco Históricos"** — historial de tasas aplicadas por fecha.

---

## 4. Emisión de documentos de venta (Factura, Nota de Crédito/Débito)

### 4.1 Crear y timbrar una factura

En el formulario de Factura (Contabilidad → Clientes → Facturas, o desde una Orden de Venta):

1. Con la factura en borrador, active **"Emitir Documentos"** (`use_documents`) si el diario lo permite.
2. Elija el **"Siguiente"** tipo de documento (`journal_document_class_id`) — p. ej. Factura Electrónica Afecta.
3. Complete cliente (**Glosa descriptiva**/actividad si aplica), **Forma de pago** (Contado / Crédito / Gratuito) y **Contacto** (persona específica del cliente para el DTE).
4. Si corresponde, agregue **Descuentos / Recargos Globales** (tabla bajo las líneas de factura): elija Descuento o Recargo, Monto o Porcentaje, el valor, la razón, y sobre qué líneas aplica (afectos/exentos/no facturables).
5. Confirme la factura (botón estándar de Odoo). Al confirmar se asigna el folio SII (**"Número:"**) y el documento queda listo para enviar.

### 4.2 Enviar y consultar el estado en el SII

En la pestaña **"Electronic Invoice"**:

- **"Send XML"** — envía el documento al SII (visible mientras el estado no sea exitoso, o si fue rechazado, permitiendo reenviar).
- **"Ask for DTE"** — consulta el estado actual al SII.
- **"Download XML"** / **"Download XML Exchange"** — descarga el XML enviado / el XML de intercambio con el cliente.
- **"Envío Manual XML Intercambio"** — reenvía manualmente el XML de intercambio al cliente.
- Barra de estado (**Estado SII**, `sii_result`): Borrador → No Enviado → En cola de envío → Enviado → En Proceso → **Aceptado** / **Rechazado** / **Reparo** → Procesado → Anulado.
- Si el estado es distinto de vacío, se muestran: el mensaje de respuesta del SII, el número de lote, la imagen del timbre (PDF417) y el XML firmado.

Desde la **lista de Facturas** también puede: buscar por N° de documento SII, filtrar/agrupar por Tipo de Documento, y usar los botones de fila **"Consultar"** / **"Enviar SII"** sin abrir cada documento.

**Envío masivo:** seleccione varias facturas en la lista → menú de Acciones (⚙) → **"Enviar Documentos al SII"**. Permite editar el N° de Lote de cada una y marcar **"Es set de pruebas"** (oculto y forzado si el ambiente es certificación).

### 4.3 Reclamo del cliente sobre un documento aceptado

Pestañas visibles una vez el documento fue procesado por el SII:

- **"Registro de Reclamo en SII"** — botón **"Consultar estado de Reclamo"** y barra de estado (`claim`): Acepta Contenido del Documento (ACD), Reclamo al Contenido (RCD), Otorga Recibo de Mercaderías (ERM), Reclamo por Falta Parcial/Total de Mercaderías (RFP/RFT), DTE Pagado al Contado (PAG), etc.
- **"Respuesta Cliente"** — historial de respuestas recibidas del cliente sobre ese documento.

### 4.4 Notas de Crédito y Notas de Débito

Se generan con el flujo estándar de Odoo ("Add Credit Note"/Nota de Crédito desde una factura publicada), que este módulo extiende con una opción chilena:

1. En el asistente, elija el método de reverso **"Rectificativa modo chileno"** (en vez de los métodos genéricos de Odoo).
2. Elija el **Tipo de nota**: Nota de Crédito o Nota de Débito (o sus variantes de exportación, 111/112, si el documento original era de exportación).
3. Elija el motivo (`cl_refund`):
   - **"Anula Documento de Referencia"** — anula completamente el documento original.
   - **"Corrige texto Documento Referencia"** — corrige solo un dato descriptivo (autocompleta una plantilla "Dice: / Debe Decir:").
   - **"Corrige montos"** — corrige valores.
4. Escriba el **Motivo** y confirme con **"Reverse"**.

El nuevo documento queda con la referencia (folio original, tipo y motivo) creada automáticamente en su pestaña **"Referencias"** — también editable manualmente ahí si necesita agregar referencias adicionales.

### 4.5 Impresión

- El botón estándar **Imprimir → Invoices** usa automáticamente el formato correcto: **ticket térmico** (si el documento tiene marcada la casilla **"Formato Ticket"**) o **tamaño carta** con el timbre PDF417 y el texto "Timbre Electrónico SII".
- **"Print Cedible"** — imprime la copia "cedible" del documento (solo disponible una vez publicado).
- **"Imprimir Copia y Cedible"** — imprime el original y la copia cedible juntos en un solo PDF.

### 4.6 Facturas y Notas de Exportación

Los tipos 110 (Factura de Exportación), 111 (Nota de Débito) y 112 (Nota de Crédito) se emiten con el mismo selector de tipo de documento que cualquier otro — no hay pantalla separada. El único campo adicional relevante es **"Indicador de Servicio"** (para servicios calificados como exportación por Aduana). Al generar una Nota de Crédito/Débito desde una factura de exportación, el asistente del punto 4.4 ofrece automáticamente los códigos 111/112 en vez de los nacionales.

### 4.7 Documentos desde una Orden de Venta

En la Orden de Venta puede preseleccionar el **Diario** y el **tipo de documento DTE** que se usará al facturar, y registrar referencias DTE anticipadas (pestaña **"Referencias DTE"**) que se trasladan automáticamente a la factura generada.

### 4.8 Guía de Despacho Electrónica

Este módulo **no emite Guías de Despacho** (código 52) — esa función corresponde al módulo complementario `l10n_cl_stock_picking`, o a `l10n_cl_dte_point_of_sale` si la guía se emite desde el POS.

---

## 5. Recepción de documentos de proveedores (XML)

### 5.1 Recepción automática por correo

Configure el alias de correo en Ajustes (**"DTE EMail"**, ver 3.1). Cuando llega un correo con un XML adjunto a esa dirección, Odoo lo detecta y procesa automáticamente, sin intervención del usuario. Hay además una tarea programada de respaldo que revisa cada 5 minutos los últimos correos por si alguno no se procesó al llegar.

También puede forzar la búsqueda inmediata con el botón **"Buscar XML Correo"**, disponible en la lista de "Aceptar o Rechazar Documentos" (ver 5.3).

### 5.2 Subir un XML manualmente

**Contabilidad → Recepcionar XML Intercambio → "Subir XML De Envío"** (también accesible desde Compras → Aprovisionamiento).

1. Suba el archivo (`xml_file`) — el sistema muestra automáticamente cuántos documentos DTE contiene.
2. Elija **Acción**: **"Crear Orden de Pedido y Factura"** o **"Crear Solamente Factura"**.
3. Elija **"Solo Subir"** / **"Aceptar"** / **"Rechazar"**, y el **Tipo**: Ventas o Compras.
4. Si deja marcado **"Pre Documento"** (checkbox activo por defecto), el sistema solo deja el documento en borrador para revisión (ver 5.3) en vez de crear directamente una factura.
5. Opcionalmente, vincule con una **Orden de Compra a Validar** existente para conciliar líneas.
6. Confirmar. Según la configuración, se crea una Orden de Compra, una factura de proveedor en borrador, o un registro pendiente de revisión.

### 5.3 Cola de revisión — "Aceptar o Rechazar Documentos"

**Contabilidad → Recepcionar XML Intercambio → "Aceptar o Rechazar Documentos"** — esta es la pantalla de trabajo diario para el equipo de Compras/Contabilidad.

Lista de documentos recibidos en estado **Recibido** (borrador), con columnas: Fecha, Tipo Documento, Folio, Proveedor (o "Proveedor Nuevo" si aún no existe en Odoo), Monto, Estado.

Por cada fila (mientras esté en Recibido):
- **"Aceptar"** — acepta el documento tal cual.
- **"Rechazar"** — lo rechaza.
- **"Reclamo Avanzado"** — abre el asistente completo (ver 5.4) para elegir con precisión qué respuesta enviar al SII/proveedor.

El formulario de cada documento tiene, además de los datos y líneas editables, una pestaña **"XML DTE"** (para inspeccionar el XML crudo si hay dudas) y **"Registro de Reclamo"** con el historial de reclamos y el botón **"Get Claim Result"** para consultar el resultado.

> Si un documento queda sin acción durante 8 días, el sistema lo acepta automáticamente.

### 5.4 Reclamo avanzado — las respuestas formales al SII

El asistente **"Reclamo Avanzado"** (también disponible como acción masiva **"Validar Documentos"** / **"Aceptar / Rechazar Documentos"** desde la lista de Facturas de proveedor) permite declarar con precisión:

- **Operación**: Recibo de mercaderías / Aprobar comercialmente / Realizar ambas operaciones.
- **Estado del documento**: DTE Recibido Ok / Aceptado con Discrepancia / DTE Rechazado.
- **Reclamo hacia el SII** (elegir uno): No enviar reclamo, **ACD** (Acepta Contenido del Documento), **RCD** (Reclamo al Contenido del Documento), **ERM** (Otorga Recibo de Mercaderías o Servicios), **RFP** (Reclamo por Falta Parcial de Mercaderías), **RFT** (Reclamo por Falta Total de Mercaderías), **PAG** (DTE Pagado al Contado).
- Motivo del reclamo (obligatorio salvo estado "Recibido Ok").

### 5.5 Procesamiento y aceptación masiva

Sobre la lista de documentos recibidos (`mail.message.dte`), la acción **"Procesar DTEs recibidos"** permite, sobre varios seleccionados a la vez: **Crear** (staging), **Crear Aceptar Todos** o **Crear Rechazar Todos**.

Sobre la lista de "Pre Documentos" en revisión, la acción **"Aceptar DTEs recibidos"** acepta en bloque todos los seleccionados sin revisión individual.

---

## 6. Libros y reportes periódicos

### 6.1 Consumo de Folios

**Contabilidad → Informes → "Consumo de Folios"** (solo Contabilidad: Administrador).

1. Cree un registro nuevo, indique **Fecha Inicio** (la Fecha Final se autocompleta igual) y la **Compañía**.
2. El sistema **selecciona automáticamente** las boletas (39/41) y notas de crédito de boleta (61) de ese día — no se eligen manualmente.
3. Revise las pestañas **"Movimientos"** (documentos incluidos) y **"Anulaciones Manuales de Folio"** (para declarar folios físicos anulados, si aplica).
4. **"Validate"** → **"Send XML"** → **"Ask for DTE"** para confirmar la aceptación del SII.

No se pueden crear Consumos de Folios de fechas futuras. Al validar uno, cualquier otro consumo pendiente del mismo día queda automáticamente Anulado.

### 6.2 Libro de Compra / Venta

**Contabilidad → Informes → "Libros Cierre de Mes"** (solo Contabilidad: Administrador).

1. Indique **Periodo Tributario** (AAAA-MM), **Tipo de operación** (Compras/Ventas/Boleta Electrónica), **Tipo de Libro** (Mensual/Especial/Rectifica) y **Tipo de Envío** (Total/Parcial/Ajuste).
2. Al elegir el período, el sistema **autocompleta** los movimientos del período (pestaña "Movimientos"; y para Ventas, también la pestaña "Boletas" con los rangos consumidos).
3. **"Validate"** → **"Send XML"** → **"Ask for DTE"**, igual que el Consumo de Folios.
4. Reportes imprimibles disponibles: **"Libro xls"** (Excel) y **"Libro CV PDF"**.

### 6.3 Libro de Honorarios

Cubre boletas de honorarios (código 71) de forma **parcial**: se pueden registrar emisiones/recepciones, pero **no existe aún recepción automática de XML** para este tipo de documento (confirmado en el README del módulo). Además, esta pantalla no tiene un ítem de menú asignado por defecto — un administrador debe habilitar el acceso (Ajustes → Técnico → Acciones de Ventana) o agregarlo a un menú si la empresa la necesita.

---

## 7. Seguimiento técnico de envíos (para diagnosticar problemas)

Solo visible con el **modo Desarrollador** activado (Ajustes → Técnico):

- **Contabilidad → Configuración → SII Configuration → "XML request"** (`sii.xml.envio`) — cada sobre/envío al SII, con su propio estado (Borrador → No Enviado → Enviado → En Proceso → Aceptado/Rechazado). Si un envío fue **rechazado**: abra el registro, lea el mensaje de respuesta del SII (`sii_xml_response`, o la pestaña "Respuesta Email SII"), corrija lo que corresponda en los documentos de origen, y presione **"Send XML"** de nuevo para reintentar con el mismo sobre. También existe **"Solicitar Reenvío Email SII"** para pedir que el SII reenvíe su respuesta por correo si se perdió.
- **Contabilidad → Configuración → SII Configuration → "Cola de envío"** (`sii.cola_envio`) — cola interna de trabajos pendientes de envío/consulta al SII; no tiene botón de reintento manual ni muestra el error — para depurar un envío fallido, revise mejor el "XML request" correspondiente.

---

## 8. Portal público de boletas

URL: **`/boleta`** — no requiere iniciar sesión.

1. El cliente elige el tipo (Boleta Afecta o Exenta), ingresa el **N° de Boleta** y la **Fecha**.
2. Si se encuentra, ve el documento completo (con timbre) y puede presionar **"Descargar PDF"**.
3. Si no se encuentra, puede intentar nuevamente.

Rutas de descarga adicionales (requieren usuario interno con sesión iniciada): descarga del XML de una factura, del XML de intercambio, del XML del Consumo de Folios, y del XML del Libro de Compra/Venta — útiles para auditoría o para reenviar manualmente un documento a un tercero.

---

## 9. Notificaciones automáticas

El sistema puede mostrar notificaciones emergentes espontáneas mientras se trabaja en Odoo, entre ellas:

- Certificado digital **vencido** o **próximo a vencer** (≤30 días) — solo a los usuarios autorizados en la Firma correspondiente.
- **Documento Rechazado** o **Anulado** por el SII, al validar un envío.
- **Alerta sobre Folios** — cuando quedan pocos folios CAF disponibles para algún tipo de documento.
- Errores de conexión con **apicaf.cl** o con el servicio de verificación remota de contactos.

---

## 10. Tareas programadas (automáticas, sin intervención manual)

Estas corren solas en segundo plano; se listan aquí para que el equipo entienda qué hace el sistema automáticamente si algo parece "tardar":

| Tarea | Frecuencia | Qué hace |
|---|---|---|
| Cron Descarga Correos DTE Proveedores | cada 5 min | Revisa el correo configurado y procesa los XML recibidos. |
| Cron de envío y consulta estado documento en el SII | cada 1 min | Envía DTE pendientes y consulta el estado de los ya enviados (motor de la Cola de envío). |
| Cron AutoAceptación Documentos | diaria, 08:00 | Acepta automáticamente documentos de proveedor sin respuesta manual tras el plazo (hasta 50 por corrida). |
| Cron Verificación de Partners | diaria, 08:00 | Actualiza datos de contactos contra el registro remoto. |
| Cron Alerta Vencimiento Certificados Digitales | diaria, 09:00 | Dispara las alertas de certificado por vencer/vencido. |
| Cron AutoReponer CAF | cada 1 min | Gestiona la reposición automática de folios cuando quedan pocos. |

---

## 11. Roles y permisos

| Acción | Quién puede hacerla |
|---|---|
| Subir/editar Firma Electrónica (certificado digital) | Solo Administrador (`base.group_system`) |
| Acceder a "Configuraciones DTE" en Ajustes | Solo Administrador |
| Subir/editar CAF | Cualquier usuario interno |
| Solicitar/anular folios vía apicaf.cl | Usuarios con permiso de Facturación (`account.group_account_invoice`) |
| Configurar diario (Create Journal Documents) | Usuarios con permiso de Facturación |
| Editar catálogos SII (tipos de documento, responsabilidades, etc.) | Contabilidad: Administrador (`account.group_account_manager`) |
| Recepción/aceptación/rechazo de XML de proveedores, envío masivo, reclamos | Usuarios con permiso de Facturación |
| Generar y validar Libro de Compra/Venta y Libro de Honorarios | Solo Contabilidad: Administrador |
| Ver "Cola de envío" y "XML request" | Requiere modo Desarrollador activo |

---

## 12. Preguntas frecuentes y mensajes de error comunes

**"Your company has not setted any responsability..."**
Falta configurar la Responsabilidad Tributaria de la empresa (sección 3.1) antes de poder crear documentos en un diario.

**El asistente de folios (apicaf) muestra "Usuario Baneado temporalmente"**
Use el botón **"Remover Bloqueo (Ban)"** que aparece junto al mensaje de error.

**"Debe instalar la dependencia python PyMuPDF..."**
Solo ocurre al sincronizar MEPCO desde el PDF del Diario Oficial; instale `PyMuPDF`/`pytesseract` (ver sección 1) o cambie el origen a "Manual"/"Página del SII".

**Un documento de proveedor no llegó automáticamente por correo**
Verifique que el alias "DTE EMail" esté bien configurado en Ajustes, o use **"Subir XML De Envío"** para cargarlo manualmente, o el botón **"Buscar XML Correo"** en la lista de recepción para forzar la revisión inmediata.

**Un envío al SII quedó "Rechazado"**
Abra el registro correspondiente en **"XML request"** (modo desarrollador), lea el mensaje de respuesta del SII, corrija el documento de origen y presione **"Send XML"** para reintentar.

**No aparece el botón para emitir Guía de Despacho**
Este módulo no la emite — se necesita `l10n_cl_stock_picking` (o el módulo de POS si la guía sale desde el punto de venta).

---

## 13. Glosario

### Estados de envío al SII (`sii_result`)
Borrador · No Enviado · En cola de envío · Enviado · En Proceso · **Aceptado** · **Rechazado** · **Reparo** · Procesado · Anulado.

### Códigos de reclamo/respuesta (`claim`)
| Código | Significado |
|---|---|
| N/D | No enviar reclamo al SII |
| ACD | Acepta Contenido del Documento |
| RCD | Reclamo al Contenido del Documento |
| ERM | Otorga Recibo de Mercaderías o Servicios |
| RFP | Reclamo por Falta Parcial de Mercaderías |
| RFT | Reclamo por Falta Total de Mercaderías |
| PAG | DTE Pagado al Contado |
| ENC | Recepción de NC distinta de anulación |
| NCA | Recepción de NC de anulación |

### Términos SII
- **DTE** — Documento Tributario Electrónico (cualquier documento: factura, boleta, nota, etc.).
- **CAF** — Certificado de Autorización de Folios: rango de números de documento autorizado por el SII (vence a los 6 meses).
- **Folio** — Número correlativo de un documento dentro de un rango CAF.
- **Timbre Electrónico** — Sello digital (código de barras PDF417) impreso en cada DTE.
- **Libro CV** — Libro de Compra/Venta, registro mensual enviado al SII.
- **MEPCO** — Tasa mensual del impuesto específico a combustibles, publicada en el Diario Oficial.
- **RUT** — Rol Único Tributario (identificación tributaria chilena).
