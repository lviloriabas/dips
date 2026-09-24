# Extracción de DIPs de ICAM

Los programas de este directorio solo consultan ICAM. La búsqueda usa `POST /maintenix/servlet/ScanBarcode`; las fichas de DIP e inventario se leen con `GET`. No envían formularios de edición.

## Datos y estructura

La lista de barcodes sale de `02 - HISTORY - DIPs AUDIT (From 09Jul 15_45).xlsx`. `data/icam_dips.json` contiene las seis pestañas de cada DIP capturado, más las fichas de inventario enlazadas por serial cuando hay una fecha sensible. `data/dips_dataset.json` combina esos datos con el Excel. Se conservan localmente; `data/` está excluido de Git porque las fichas incluyen información operativa y nombres de empleados.

Cada elemento de `records` incluye `barcode`, `page_title`, `aircraft`, `inventory`, `header_fields` y `sections` (`TaskExecution`, `FaultInformation`, `TaskInformation`, `Scheduling`, `History`, `Warranty`). Las secciones conservan su texto y los campos estructurados de descripción, steps, referencias, attachments, intervalos y partes. `inventory_details` registra serial, rol de la pieza, Shelf-Life Expiry, Release Remarks y texto de inventario. `normalized.date_audit` indica las fechas encontradas, su fuente y si coinciden con el deadline del DIP.

## Sesión existente de Edge

1. Ejecutar `python tools/build_icam_inpage_scraper.py` para generar el JavaScript con los barcodes pendientes.
2. Ejecutar `python tools/icam_json_receiver.py` para guardar lotes localmente.
3. En una pestaña de DIP de ICAM donde la sesión ya esté iniciada, ejecutar una vez el contenido de `data/icam_inpage_scraper.js` en la consola de Edge. El script consulta tres DIPs en paralelo y guarda cada diez registros. Si el navegador bloquea el receptor local, descargará un JSON; incorporarlo con `python tools/import_icam_download.py <archivo>`.
4. Ejecutar `python tools/build_dips_dataset.py` para actualizar la vista normalizada.

`node tools/test_icam_inpage_scraper.mjs` comprueba la extracción contra páginas simuladas; no consulta ICAM. `node tools/scrape_icam.mjs --self-test` comprueba el parser del programa independiente.

## Programa independiente

`node tools/scrape_icam.mjs --concurrency 3` abre una sesión aislada de Edge y espera que alguien inicie sesión una vez. Si Edge ya expone un puerto de depuración, `node tools/scrape_icam.mjs --cdp http://127.0.0.1:9222` reutiliza esa ventana. El programa omite los barcodes ya guardados, reintenta errores transitorios y conserva el avance cada diez fichas. El perfil habitual de Edge en este equipo no expuso el puerto de depuración al probarlo.
