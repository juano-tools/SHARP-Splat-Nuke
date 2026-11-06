"""SHARP Splat para Nuke 17: un cuadro del plate -> Gaussian splats HDR (SHARP-HDR en ComfyUI)."""

__version__ = "0.1.0"


def register():
    import nuke
    if nuke.NUKE_VERSION_MAJOR < 17:  # SplatRender y GeoReference existen desde Nuke 17
        return
    nuke.menu("Nodes").addCommand("3D/SHARP Splat", "import sharp_splat.node as n; n.create()")
