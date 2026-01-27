from asgiref.wsgi import WsgiToAsgi

from .app import app as flask_app


def new():
    return Function()


class Function:
    def __init__(self):
        self._asgi_app = WsgiToAsgi(flask_app)

    async def handle(self, scope, receive, send):
        await self._asgi_app(scope, receive, send)

    def alive(self):
        return True, "alive"

    def ready(self):
        return True, "ready"
