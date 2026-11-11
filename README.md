# SHARP Splat para Nuke

Convierte un cuadro de un plate en una escena 3D de Gaussian splats, en HDR y en metros, lista para renderizar desde otra cámara en Nuke 17. Usa [SHARP](https://github.com/apple/ml-sharp) en ComfyUI, a través de [ComfyUI-SHARP-HDR](https://github.com/metalrahul/ComfyUI-SHARP-HDR) de metalrahul (ver *Créditos*).

Para un recorrido paso a paso con un plano de ejemplo, mira el [tutorial](TUTORIAL.md).

Sirve para mover un poco la cámara sobre un plano fijo (parallax, pequeños dolly o reencuadres), para tener una referencia 3D del set o para proyectar.

## Qué necesitas

- **Nuke 17 o más nuevo** (NukeX). SplatRender no existe en versiones anteriores.
- **ComfyUI instalado en el mismo PC**: Comfy Desktop o ComfyUI portable. No hace falta abrirlo. Al apretar Generar, si está cerrado, el nodo lo abre sin ventana, con la misma configuración que usa Comfy Desktop (la primera vez tarda cerca de un minuto), y lo cierra al cerrar Nuke. Si ya está abierto, lo usa.
  - Las instalaciones de Comfy Desktop (la app actual y la anterior) las encuentra solo. Para un ComfyUI portable o manual que Comfy Desktop no conoce, define la variable de entorno `SHARP_SPLAT_COMFYUI_DIR` con su carpeta (por ejemplo, `D:\ComfyUI_windows_portable`).
  - Si tu ComfyUI ya abierto usa una dirección distinta de los puertos 8000 u 8188, defínela en `SHARP_SPLAT_COMFYUI_URL` (por ejemplo, `http://127.0.0.1:8190`).
- **En ComfyUI**, estos tres paquetes de nodos (se instalan con ComfyUI Manager):
  - `ComfyUI-Sharp` (Pozzetti)
  - `ComfyUI-SHARP-HDR` (metalrahul)
  - `ComfyUI-HQ-Image-Save` (para leer EXR)
- **GPU NVIDIA con 10 GB de VRAM o más.** SHARP ocupa unos 9 GB.

La primera vez, ComfyUI-Sharp baja el modelo (2,8 GB). Desde la segunda vez, cada cuadro tarda unos 5 segundos.

## Instalar

1. Doble clic en `instalar.bat`.
2. El instalador copia el plugin a tu `.nuke`, agrega el menú y revisa si tienes Nuke 17. Si ComfyUI está abierto, también revisa sus nodos. Si falta algo, te lo dice en amarillo.
3. Abre Nuke 17.

Para quitarlo, usa `desinstalar.bat`.

## Usar

1. Selecciona el plate y crea el nodo desde **Nodes > 3D > SHARP Splat**. Queda conectado a la entrada `plate`.
2. Revisa el **focal** y el **ancho sensor** (el filmback: el ancho, en mm, del área del sensor que corresponde al cuadro completo). El nodo los llena si vienen en la metadata de cámara del plate. Lo que no viene queda en 0 y lo tienes que escribir. La línea `metadata` dice qué encontró y qué falta. **Si estos dos valores están mal, la escena sale deformada y con la escala equivocada.**
3. Elige el **cuadro** (por defecto, el cuadro en que creaste el nodo) y aprieta **Generar**.
4. La salida del nodo es el render de los splats. Desde la cámara original tiene que calzar con el plate.

### Sacar la escena del nodo

En **sacar**, elige qué quieres y aprieta **Crear**, como en el Export del CameraTracker:

- **Cámara**
- **Cámara + splats**: un GeoReference con el PLY y un GeoTransform.
- **Cámara + splats + proxy**: además, la malla proxy (ReadGeo y TransformGeo).
- **Escena completa (con SplatRender)**: todo lo anterior, ya conectado a un SplatRender propio.

Lo que sale queda en el mundo nivelado, con valores fijos y sin enlaces al nodo, así que lo puedes mover, combinar o borrar sin tocar el nodo.

Si en el viewer 3D los splats se ven muy oscuros, marca **splats en Rec.709 (previs)** antes de apretar Crear: los splats que salen usan una copia del PLY con el color convertido a Rec.709 de pantalla. Es solo para mirar: ese color ya no es lineal y no sirve para render.

### Ver desde otra cámara

Saca la **Cámara**, duplícala o anímala y conéctala a la entrada `cam`. Mientras `cam` tenga algo conectado, el nodo renderiza desde esa cámara. Los movimientos chicos se ven bien; si la cámara se aleja mucho, aparece lo que el plate nunca mostró (estirado o vacío).

### Escena nivelada y en metros

Con **nivelar piso** marcado (viene así), el nodo busca el piso bajo la cámara, lo deja horizontal en Y = 0 y pone el origen justo debajo de la cámara. La línea `estado` muestra la altura de la cámara y su inclinación.

SHARP ya entrega metros si el focal y el ancho de sensor son los reales. Si conoces la altura real de la cámara, escríbela en **altura cámara (m)** y la escena se escala para que calce. El render desde la cámara original no cambia con ninguna de las dos opciones.

En planos sin piso bajo la cámara (cenitales, primeros planos), la nivelación no lo encuentra y la escena queda como la entrega SHARP.

Para corregir a mano usa **girar escena (°)** y **mover escena (m)**, que se suman a la nivelación. En el giro, X corrige el tilt, Z el roll e Y gira la escena sobre el eje vertical (por ejemplo, para alinear una calle con Z). También sirven con **nivelar piso** desmarcado, para orientar todo a mano. Mover estos controles no cambia el render desde la cámara de SHARP, porque la cámara se mueve con la escena.

### Recortar

SHARP a veces manda splats al infinito, sobre todo en luces quemadas (un difusor blanco en el techo) o en el cielo. En la sección **recortar**, marca **recortar**: se borran los splats que quedan fuera de la **caja (m)**. La primera vez la caja se ajusta sola a la escena, con los splats que están a menos de 3 veces la distancia mediana a la cámara. **ajustar a la escena** la vuelve a poner así.

La caja está en metros del mundo nivelado (piso en Y = 0, la cámara mira hacia -Z): mínimo y máximo en X, Y y Z. Si giras o mueves la escena, la caja se queda fija en el mundo y cambia lo que queda dentro. Al lado de la caja aparece cuántos splats quedan.

El recorte escribe una copia del PLY (`..._crop_<código>.ply`, junto al original) y el nodo la usa en vez del original. Cada caja tiene su propia copia: lo que sacas con **Crear** se queda con la que tenía, aunque después cambies la caja. Mientras arrastras la caja, el recorte espera a que la sueltes. Las copias que ya no usa ningún nodo se borran solas.

### Cards sobre una superficie

En la sección **card sobre una superficie**, aprieta **Nueva card**: se crea afuera un GeoCard pegado a la superficie bajo el **punto**. Con el panel del nodo abierto, arrastra el punto en el viewer (sobre una pared, el piso o un letrero) y la card lo sigue: queda sobre esa superficie y orientada con ella. En paredes, el borde de abajo queda horizontal. Una **grilla** dibujada sobre la salida del nodo muestra dónde queda la card (se apaga con **ver grilla**).

- **radio de lectura (px)**: de cuánta superficie alrededor del punto se lee la orientación. Más grande es más estable; para objetos chicos (un letrero, un marco) conviene achicarlo hasta que cubra solo el objeto.
- **tamaño (m)**: ancho y alto de la card. Al crearla, el nodo le da un tamaño que cubre el radio.
- **girar en el plano (°)**: gira la card sobre su superficie.
- **enderezar** (viene marcado): en el mundo nivelado, las paredes quedan exactamente verticales y los pisos exactamente horizontales. Quita el cabeceo que deja el ruido de profundidad. Desmárcalo para superficies inclinadas, como la carrocería de un auto.

La orientación sale de la superficie visible bajo el punto (la capa de adelante de los splats), así que un objeto que tapa a otro gana aunque sea más chico. Si el punto cae en un borde entre dos superficies, la card se pega a la de adelante. El label de la card muestra su tamaño y a qué distancia está. La última card creada es la que sigue al punto; con otra **Nueva card**, la anterior queda fija.

La grilla solo se dibuja cuando el nodo renderiza desde la cámara de SHARP; con otra cámara en `cam`, se apaga.

### Aislar un objeto

En **modo**, elige *Aislar objeto (alpha)*: SHARP usa el alpha del plate y solo genera lo que está dentro. Los ajustes de la sección *aislar objeto* afinan el borde. Los objetos aislados quedan como cartones delgados si los miras de lado.

### Ajustes de SHARP

Están en tres grupos: *splats*, *malla proxy* y *aislar objeto*. Cada uno tiene una descripción al dejar el mouse encima. Por dentro conservan el nombre de ComfyUI-SHARP-HDR. Después de cambiarlos, aprieta **Generar** otra vez.

## Créditos

Este paquete es solo la parte de Nuke. El trabajo de fondo es de:

- [ComfyUI-SHARP-HDR](https://github.com/metalrahul/ComfyUI-SHARP-HDR), de metalrahul: los splats en HDR, el PLY y la escena para Nuke que este nodo arma por dentro.
- [ComfyUI-Sharp](https://github.com/PozzettiAndrea/ComfyUI-Sharp), de PozzettiAndrea: SHARP en ComfyUI.
- [SHARP](https://github.com/apple/ml-sharp), de Apple: el modelo.
- [ComfyUI-HQ-Image-Save](https://github.com/spacepxl/ComfyUI-HQ-Image-Save), de spacepxl: la lectura del EXR.

## Dónde quedan los archivos

- El cuadro exportado en EXR va a `sharp_splat\` junto al script de Nuke. Si el script no está guardado, va a `%TEMP%\sharp_splat\`.
- Los splats (PLY, unos 130 MB por corrida) y el resto de lo que genera SHARP quedan en la carpeta `output` de ComfyUI. Cada vez que aprietas Generar se crea una versión nueva y no se borra ninguna, así que hay que limpiar esa carpeta de vez en cuando.

## Problemas conocidos

- **No se puede cancelar a mitad.** Cancelar el /interrupt de ComfyUI deja colgado al worker de ComfyUI-Sharp. Cada corrida dura unos 5 segundos, así que hay que esperar que termine.
- Si una corrida queda "calculando..." para siempre, cierra y vuelve a abrir Nuke: si el nodo abrió ComfyUI, se cierra con Nuke y se vuelve a abrir al apretar Generar. Si lo abriste tú, reinícialo.
- Si ComfyUI no abre, el error muestra la ruta de su log (`sharp_splat_comfyui.log`, en la carpeta temporal de Windows).
- Si alguien abre el script sin el plugin instalado, el nodo sigue renderizando con la última versión, pero los botones no funcionan.

## Para desarrolladores

- `nuke/sharp_splat/core.py`: lo que no depende de Nuke (metadata, workflow, PLY, piso).
- `nuke/sharp_splat/node.py`: el Group y sus botones.
- `nuke/sharp_splat/comfy.py`: el cliente de ComfyUI (encola el workflow y espera el resultado).
- `python tests/test_core.py`: pruebas sin Nuke (necesitan numpy).
- `Nuke17.1.exe -i -t --nukex tests/nuke_node_test.py <plate.####.exr> <cuadro> <focal> <carpeta>`: flujo completo con ComfyUI y la GPU.

## Licencia

MIT (ver [LICENSE](LICENSE)). Cubre el código de este paquete; SHARP, ComfyUI y los nodos de la sección Créditos tienen sus propias licencias.
