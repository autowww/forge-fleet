"""Request queue — resident-first affinity dispatcher."""

from control_plane.affinity_queue import affinity_queue, inference_queue

__all__ = ["affinity_queue", "inference_queue"]
