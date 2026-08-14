from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="ShortLink Desk")


@app.get("/", response_class=HTMLResponse)
def homepage():
    return """
    <html><head><title>ShortLink Desk</title></head>
    <body>
      <h1>ShortLink Desk</h1>
      <p>Fixture starter: implement URL shortening, review queue, stats, audit history, and persistence.</p>
    </body></html>
    """
