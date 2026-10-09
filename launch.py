"""Launch Sharingan on localhost; direct Seedance tasks use polling."""
import os
from config import load_env

if __name__ == '__main__':
    load_env()
    import uvicorn
    uvicorn.run('app:app', host='127.0.0.1', port=int(os.getenv('PORT', '8770')))
