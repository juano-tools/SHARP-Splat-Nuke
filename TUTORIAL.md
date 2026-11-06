# Tutorial: de un cuadro del plate a un movimiento de cámara

En este tutorial tomas un cuadro de un plano fijo, lo conviertes en Gaussian splats con SHARP Splat y le agregas un pequeño dolly que el plano no tenía. De paso nivelas la escena, limpias los splats que se van al infinito, pegas una card a una pared y te llevas todo al comp para seguir editándolo con nodos de Nuke.

Toma unos 15 minutos. Necesitas el paquete y ComfyUI instalados, como dice el [README](README.md#qué-necesitas).

---

## 1. Elige el cuadro

SHARP trabaja con **un solo cuadro**: todo lo que genera sale de esa imagen. Antes de crear el nodo, busca en el plate el cuadro que más te sirva:

- **Nítido**, sin motion blur ni foco de paso. El desenfoque se transforma en splats blandos y en profundidad dudosa.
- **Representativo**: que se vea lo que la cámara nueva va a mostrar. Lo que el cuadro no ve, SHARP no lo inventa bien.
- **Sin gente u objetos cruzando**, salvo que sean parte de lo que quieres en 3D.

Las zonas quemadas (luces, difusores, ventanas, cielo blanco) no tienen textura, y SHARP suele mandarlas muy lejos. No es grave: en el paso 5 las recortas.

## 2. Crea el nodo y revisa el lente

1. Selecciona el Read del plate y crea el nodo desde **Nodes > 3D > SHARP Splat**. Queda conectado a la entrada `plate`.
2. Ve al cuadro que elegiste y aprieta **usar el actual**.
3. Revisa **focal (mm)** y **ancho sensor (mm)**. Si el plate trae metadata de cámara, el nodo ya los llenó. La línea `metadata` dice qué encontró y qué falta.

El lente es lo más importante de todo el proceso. El ancho de sensor es el del **área grabada**, no el del sensor entero: si la cámara grabó con recorte (por ejemplo, un modo 4K en un sensor 6K), el ancho es menor. Si no hay metadata, saca los datos del reporte de cámara. Con un focal o un ancho equivocados, la escena sale deformada y con la escala mal, y ninguno de los pasos siguientes lo arregla.

Deja el **modo** en *Escena completa*. *Aislar objeto* se ve en el paso 9.

## 3. Genera y comprueba que calza

Aprieta **Generar**. Si ComfyUI está cerrado, el nodo lo abre sin ventana: eso suma cerca de un minuto, solo la primera vez en cada sesión de Nuke. La primera vez ComfyUI-Sharp baja el modelo (2,8 GB) y tarda más. Desde la segunda, cada cuadro toma unos 5 segundos. Mientras trabaja, la línea `estado` dice "calculando...".

La salida del nodo es el render de los splats **desde la cámara original**, así que tiene que calzar con el plate. Compruébalo así:

- Conecta el plate a la entrada A del viewer y el nodo a la B, y usa el wipe. Los bordes de los objetos tienen que coincidir en todo el cuadro, no solo al centro.
- Si calza al centro pero se abre hacia los bordes, el focal o el ancho de sensor están mal. Corrígelos y vuelve a Generar.

Cada Generar crea una versión nueva (`v001`, `v002`...) y no borra las anteriores. Mira la sección [Dónde quedan los archivos](README.md#dónde-quedan-los-archivos) del README para limpiar cuando termines.

## 4. Nivela y pon la escena a escala

Con **nivelar piso** marcado (viene así), el nodo busca el piso bajo la cámara y lo deja horizontal en Y = 0, con el origen justo debajo de la cámara. La línea `estado` muestra, por ejemplo, `cámara a 1.62 m del piso, tilt -3.1, roll 0.4`. Usa esa línea para comprobar el resultado:

- Si la altura es razonable para el plano (1,5-1,8 m en cámara en mano o en trípode a la altura de los ojos), la escala de SHARP está bien.
- Si conoces la altura real (está en el reporte de cámara o la puedes deducir del set), escríbela en **altura cámara (m)** y la escena se escala para calzar.
- Si quieres que una pared o una calle quede alineada con un eje, gira la escena con la Y de **girar escena (°)**.

Nada de esto cambia el render desde la cámara original: la cámara se mueve junto con la escena. Si el plano no muestra piso bajo la cámara (un cenital o un primer plano), la nivelación no lo encuentra y la escena queda tal como la entrega SHARP. En ese caso, oriéntala a mano con **girar escena** y **mover escena**.

## 5. Recorta lo que se fue al infinito

Abre la sección **recortar** y marca **recortar**. La primera vez, la **caja (m)** se ajusta sola alrededor de los splats que están a menos de 3 veces la distancia mediana a la cámara. Al lado aparece cuántos quedan, por ejemplo `quedan 960209 de 1179648 splats`.

Los números de la caja son el mínimo y el máximo en X, Y y Z, en metros del mundo que niveló el paso 4. La cámara mira hacia -Z, así que:

- Para recortar **más cerca de la cámara** (el fondo lejano), sube el mínimo de Z: de `-32` a `-15`, por ejemplo.
- Para recortar **el techo** o una luz quemada arriba, baja el máximo de Y.
- Para quitar **lo que está bajo el piso**, el mínimo de Y va un poco bajo 0, por ejemplo `-0.2`.

Para ver qué queda dentro, saca los splats (**sacar** → *Cámara + splats* → **Crear**) y míralos en el viewer 3D. Si la caja queda vacía, el nodo te avisa y no recorta.

Si después giras o mueves la escena, la caja se queda fija en el mundo y cambia lo que queda dentro. Conviene nivelar primero y recortar después.

## 6. Agrega el movimiento de cámara

1. En **sacar**, elige *Cámara* y aprieta **Crear**. Aparece una cámara a la derecha del nodo, en la posición original y ya en el mundo nivelado.
2. Anímala. Para un dolly in de unos 30 cm: en el primer cuadro, deja un keyframe en `translate`. En el último, réstale `0.3` a Z: la cámara mira hacia -Z, salvo que hayas girado la escena en Y en el paso 4.
3. Conéctala a la entrada `cam` del nodo. Mientras haya algo conectado ahí, el nodo renderiza desde esa cámara.

Como los splats salen de un solo cuadro, **los movimientos chicos funcionan y los grandes no**. Al alejarte de la posición original aparece lo que el plate nunca vio: detrás de los objetos quedan huecos o splats estirados. Un dolly corto, un leve arco o un reencuadre funcionan bien. Una vuelta alrededor de un objeto no funciona.

Si aparecen huecos chicos entre splats, sube un poco **tamaño** en la sección *splats* y vuelve a Generar.

## 7. Pega una card a una pared

Las cards sirven para poner un elemento sobre una superficie del plate (un letrero, una ventana, una mancha en la pared) o como base para proyectar.

1. Desconecta la entrada `cam`: la grilla de ayuda solo se ve desde la cámara original.
2. En la sección **card sobre una superficie**, aprieta **Nueva card**. Aparece un GeoCard afuera, pegado a la superficie bajo el **punto**, y una grilla naranja sobre la salida del nodo.
3. Con el panel del nodo abierto, arrastra el punto en el viewer hasta la pared. La card la sigue y se orienta con ella.
4. Ajusta **tamaño (m)** y **girar en el plano (°)**. Si la superficie es chica (un marco, un letrero), baja el **radio de lectura** hasta que cubra solo ese objeto.

**enderezar** deja las paredes exactamente verticales y los pisos exactamente horizontales. Desmárcalo para superficies inclinadas, como un techo a dos aguas o el capó de un auto.

La última card creada sigue al punto. Si aprietas Nueva card otra vez, la anterior queda fija donde estaba.

## 8. Llévalo al comp y sigue editando con Nuke

En **sacar**, elige *Escena completa (con SplatRender)* y aprieta **Crear**. Sale una copia con la cámara, los splats (GeoReference + GeoTransform), la malla proxy y un SplatRender propio, ya conectados. Esa copia tiene valores fijos y no está enlazada al nodo, así que puedes editarla sin tocar el nodo.

Los splats son nativos de Nuke 17, así que les puedes aplicar sus nodos 3D. Ponlos entre el GeoTransform y el SplatRender:

- **Borrar una zona**: un **GeoDeletePoints** con un **FieldShape** en la entrada *mask*. Elige forma *Box*, ubica la caja en el viewer 3D y marca **Invert Points Mask** para borrar lo que queda **fuera** de la caja. Desmárcalo para borrar lo que queda **dentro**, por ejemplo una lámpara. En nuestras pruebas la forma *Box* funcionó bien, pero con *Sphere* los resultados no fueron confiables: revisa siempre el resultado.
- **Mover, girar o escalar** una parte o todo: **GeoTransform**.
- **Proyectar** sobre la malla proxy (ReadGeo y TransformGeo de la copia): sirve cuando necesitas una superficie sólida en vez de splats.

Dos detalles:

- Si marcaste **recortar**, los splats que salen usan la copia recortada (`..._crop.ply`). Lo que sacaste se queda con ese recorte aunque después cambies la caja en el nodo.
- **splats en Rec.709 (previs)** sirve solo para mirar los splats en el viewer 3D con un color parecido al del monitor. Para render, déjalo desmarcado: ese color ya no es lineal.

## 9. Variante: aislar un objeto

Si solo quieres un objeto en 3D (un auto, una persona, un mueble):

1. Dale al plate un alpha del objeto, con roto o un key.
2. En **modo**, elige *Aislar objeto (alpha)* y aprieta Generar.
3. Si el borde trae fondo pegado, ajusta la sección *aislar objeto*: **achicar borde (px)** y **quitar negros** son los primeros que conviene probar. Cada control tiene una descripción al dejar el mouse encima.

El objeto aislado sale como un cartón con volumen hacia la cámara. Sirve para movimientos chicos, no para verlo de lado.

---

## Si algo sale mal

| Qué ves | Qué hacer |
|---|---|
| El render no calza con el plate hacia los bordes | Revisa focal y ancho de sensor (paso 2) y vuelve a Generar. |
| `estado`: "No encontré piso bajo la cámara." | No hay piso visible bajo la cámara. Orienta a mano (paso 4). |
| La cámara queda a una altura absurda | La escala de SHARP no calza: escribe la altura real en **altura cámara (m)**. |
| Splats sueltos muy lejos o una "cortina" detrás de todo | Recorta (paso 5). |
| Huecos entre splats al mover la cámara | Sube **tamaño** en *splats*, o achica el movimiento. |
| Se queda en "calculando..." para siempre | Cierra y vuelve a abrir Nuke (el ComfyUI que abrió el nodo se cierra con Nuke). No se puede cancelar a mitad de una corrida. |
| "ComfyUI está cerrado y no encontré cómo abrirlo" | Tu ComfyUI no es de Comfy Desktop: define la variable de entorno `SHARP_SPLAT_COMFYUI_DIR` con su carpeta, o ábrelo tú antes de Generar. |
| Los splats se ven muy oscuros en el viewer 3D | Es el color lineal. Para mirarlos, saca una copia con **splats en Rec.709 (previs)**. |

Para el detalle de cada control, mira el [README](README.md). Las herramientas sobre las que trabaja este paquete están en la sección [Créditos](README.md#créditos).
