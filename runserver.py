#!/usr/bin/env python
import uvicorn

from mysite.routing import app

uvicorn.run(app, host='0.0.0.0', port=8000)
