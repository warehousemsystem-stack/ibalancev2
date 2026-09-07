"""ibalance - Sincronizador de PLUs con balanzas Rongta RLS-1000/1100.

La comunicacion con las balanzas NO se hace por sockets propios: se delega en la
libreria nativa de Windows ``rtslabelscale.dll`` (32 bits) a traves de ctypes.
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
