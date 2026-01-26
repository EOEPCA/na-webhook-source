from .func import new


async def handle(scope, receive, send):
    fn = new()
    await fn.handle(scope, receive, send)
