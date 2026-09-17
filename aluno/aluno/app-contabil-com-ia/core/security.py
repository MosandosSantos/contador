import secrets
from datetime import timedelta
from flask import request, session, abort

def csrf_token():
    if 'csrf_token' not in session: session['csrf_token']=secrets.token_hex(32)
    return session['csrf_token']

def init_security(app):
    production=app.config['PRODUCTION']
    app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=production,PERMANENT_SESSION_LIFETIME=timedelta(hours=2),MAX_CONTENT_LENGTH=12*1024*1024)
    @app.before_request
    def validate():
        if request.method in ('POST','PUT','PATCH','DELETE'):
            sent=request.form.get('csrf_token') or request.headers.get('X-CSRF-Token','') or request.headers.get('X-CSRFToken','')
            if not sent or not secrets.compare_digest(sent,session.get('csrf_token','')):abort(400,description='Sua sessão expirou. Atualize a página e tente novamente.')
    @app.after_request
    def headers(response):
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
        if production:response.headers['Strict-Transport-Security']='max-age=31536000'
        if not request.path.startswith('/static/'):response.headers['Cache-Control']='no-store'
        return response
