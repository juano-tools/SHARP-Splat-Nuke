# SHARP Splat para Nuke

Convierte un cuadro de un plate en una escena 3D de Gaussian splats, en HDR y en metros, lista para renderizar desde otra cámara en Nuke 17. Usa [SHARP](https://github.com/apple/ml-sharp) en ComfyUI, a través de ComfyUI-SHARP-HDR.

Sirve para mover un poco la cámara sobre un plano fijo (parallax, pequeños dolly o reencuadres), para tener una referencia 3D del set o para proyectar.

## Qué necesitas

- **Nuke 17 o más nuevo** (NukeX). SplatRender no existe en versiones anteriores.
- **GenFill del estudio**, instalado y conectado a tu ComfyUI. SHARP Splat usa esa misma conexión, y si ComfyUI Desktop está cerrado, lo abre.
- **En ComfyUI**, estos tres paquetes de nodos (se instalan con ComfyUI Manager):
  - `ComfyUI-Sharp` (Pozzetti)
  - `ComfyUI-SHARP-HDR` (metalrahul)
  - `ComfyUI-HQ-Image-Save` (para leer EXR)
- **GPU NVIDIA con 10 GB de VRAM o más.** SHARP ocupa unos 9 GB.

La primera vez, ComfyUI-Sharp baja el modelo (2,8 GB). Desde la segunda vez, cada cuadro tarda unos 5 segundos.

## Instalar

1. Doble clic en `instalar.bat`.
2. El instalador copia el plugin a tu `.nuke`, agrega el menú y revisa si tienes Nuke 17, GenFill y los nodos de ComfyUI. Si falta algo, te lo dice en amarillo.
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

### Ver desde otra cámara

Saca la **Cámara**, duplícala o anímala y conéctala a la entrada `cam`. Mientras `cam` tenga algo conectado, el nodo renderiza desde esa cámara. Los movimientos chicos se ven bien; si la cámara se aleja mucho, aparece lo que el plate nunca mostró (estirado o vacío).

### Escena nivelada y en metros

Con **nivelar piso** marcado (viene así), el nodo busca el piso bajo la cámara, lo deja horizontal en Y = 0 y pone el origen justo debajo de la cámara. La línea `estado` muestra la altura de la cámara y su inclinación.

SHARP ya entrega metros si el focal y el ancho de sensor son los reales. Si conoces la altura real de la cámara, escríbela en **altura cámara (m)** y la escena se escala para que calce. El render desde la cámara original no cambia con ninguna de las dos opciones.

En planos sin piso bajo la cámara (cenitales, primeros planos), la nivelación no lo encuentra y la escena queda como la entrega SHARP.

Para corregir a mano usa **girar escena (°)** y **mover escena (m)**, que se suman a la nivelación. En el giro, X corrige el tilt, Z el roll e Y gira la escena sobre el eje vertical (por ejemplo, para alinear una calle con Z). También sirven con **nivelar piso** desmarcado, para orientar todo a mano. Mover estos controles no cambia el render desde la cámara de SHARP, porque la cámara se mueve con la escena.

### Cards sobre una superficie

En la sección **card sobre una superficie**, aprieta **Nueva card**: se crea afuera un GeoCard. Con el panel del nodo abierto, mueve las 4 esquinas en el viewer alrededor de una superficie del plate (una pared, el piso, un letrero). La card se ajusta sola mientras arrastras: queda sobre esa superficie, orientada con ella y del tamaño de la región, en el mundo del nodo. El label de la card muestra su tamaño en metros y qué parte de los splats de la región cae en el plano; si es bajo, la región mezcla superficies.

La última card creada es la que sigue a las esquinas. Si aprietas **Nueva card** otra vez, la anterior queda fija y la nueva pasa a seguir las esquinas. Las cards también se reajustan si cambias la nivelación, el giro o la posición de la escena.

### Aislar un objeto

En **modo**, elige *Aislar objeto (alpha)*: SHARP usa el alpha del plate y solo genera lo que está dentro. Los ajustes de la sección *aislar objeto* afinan el borde. Los objetos aislados quedan como cartones delgados si los miras de lado.

### Ajustes de SHARP

Están en tres grupos: *splats*, *malla proxy* y *aislar objeto*. Cada uno tiene una descripción al dejar el mouse encima. Por dentro conservan el nombre de ComfyUI-SHARP-HDR. Después de cambiarlos, aprieta **Generar** otra vez.

## Dónde quedan los archivos

- El cuadro exportado en EXR va a `sharp_splat\` junto al script de Nuke. Si el script no está guardado, va a `%TEMP%\sharp_splat\`.
- Los splats (PLY, unos 130 MB por corrida) y el resto de lo que genera SHARP quedan en la carpeta `output` de ComfyUI. Cada vez que aprietas Generar se crea una versión nueva y no se borra ninguna, así que hay que limpiar esa carpeta de vez en cuando.

## Problemas conocidos

- **No se puede cancelar a mitad.** Cancelar el /interrupt de ComfyUI deja colgado al worker de ComfyUI-Sharp. Cada corrida dura unos 5 segundos, así que hay que esperar que termine.
- Si una corrida queda "calculando..." para siempre, reinicia ComfyUI.
- Si alguien abre el script sin el plugin instalado, el nodo sigue renderizando con la última versión, pero los botones no funcionan.

## Para desarrolladores

- `nuke/sharp_splat/core.py`: lo que no depende de Nuke (metadata, workflow, PLY, piso).
- `nuke/sharp_splat/node.py`: el Group y sus botones.
- `python tests/test_core.py`: pruebas sin Nuke (necesitan numpy).
- `Nuke17.1.exe -i -t --nukex tests/nuke_node_test.py <plate.####.exr> <cuadro> <focal> <carpeta>`: flujo completo con ComfyUI y la GPU.
