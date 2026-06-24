# route_frontend_authentication.py

from unittest import result
from config import *
from functions_activity_logging import log_user_login, record_user_login_session_activity
from functions_authentication import _build_msal_app, _load_cache, _save_cache, clear_requested_oauth_scopes, get_requested_oauth_scopes
from functions_debug import debug_print
from swagger_wrapper import swagger_route, get_auth_security

def build_front_door_urls(front_door_url):
    """
    Build home and login redirect URLs from a Front Door base URL.
    
    Args:
        front_door_url (str): The base Front Door URL (e.g., https://myapp.azurefd.net)
    
    Returns:
        tuple: (home_url, login_redirect_url)
    """
    if not front_door_url:
        return None, None
    
    # Remove trailing slash if present
    base_url = front_door_url.rstrip('/')
    
    # Build the URLs
    home_url = base_url
    login_redirect_url = f"{base_url}/getAToken"
    
    return home_url, login_redirect_url

def register_route_frontend_authentication(app):
    @app.route('/login')
    @swagger_route(security=get_auth_security())
    def login():
        try:
            # Clear potentially stale cache/user info before starting new login
            session.pop("user", None)
            session.pop("token_cache", None)
            session.pop("last_activity_epoch", None)
            clear_requested_oauth_scopes()

            # Use helper to build app (cache not strictly needed here, but consistent)
            debug_print(f"[LOGIN] Building MSAL app with AUTHORITY: {AUTHORITY}")
            msal_app = _build_msal_app()
            debug_print(f"[LOGIN] MSAL app built successfully")
            
            # Get settings from database, with environment variable fallback
            from functions_settings import get_settings
            settings = get_settings() or {}
            
            # Only use Front Door redirect URL if Front Door is enabled
            if settings.get('enable_front_door', False):
                front_door_url = settings.get('front_door_url')
                if front_door_url:
                    home_url, login_redirect_url = build_front_door_urls(front_door_url)
                    redirect_uri = login_redirect_url
                else:
                    # Fall back to environment variable if Front Door is enabled but no URL is set
                    redirect_uri = LOGIN_REDIRECT_URL or url_for('authorized', _external=True, _scheme='https')
            else:
                redirect_uri = url_for('authorized', _external=True, _scheme='https')
            
            debug_print(f"[LOGIN] Using redirect_uri: {redirect_uri}")
            debug_print(f"[LOGIN] CLIENT_ID: {CLIENT_ID}")
            debug_print(f"[LOGIN] SCOPE: {SCOPE}")

            debug_print(f"[LOGIN] Calling get_authorization_request_url()...")
            auth_url = msal_app.get_authorization_request_url(
                scopes=SCOPE, # Use SCOPE from config (includes offline_access)
                redirect_uri=redirect_uri
            )
            debug_print(f"[LOGIN] Auth URL generated successfully: {auth_url[:100]}...")
            print("Redirecting to Azure AD for authentication.")
            #auth_url= auth_url.replace('https://', 'http://')  # Ensure HTTPS for security
            return redirect(auth_url)
        
        except Exception as e:
            error_msg = f"Login failed: {str(e)}"
            debug_print(f"[LOGIN] ERROR: {error_msg}")
            import traceback
            traceback.print_exc()
            debug_print(f"[LOGIN] Full traceback:\n{traceback.format_exc()}")
            from functions_appinsights import log_event
            log_event("LOGIN_ERROR", {"error": str(e), "type": type(e).__name__})
            return jsonify({"error": "Authentication failed", "message": error_msg}), 500

    @app.route('/getAToken') # This is your redirect URI path
    @swagger_route(security=get_auth_security())
    def authorized():
        try:
            # Check for errors passed back from Azure AD
            if request.args.get('error'):
                error = request.args.get('error')
                error_description = request.args.get('error_description', 'No description provided.')
                error_msg = f"Azure AD Login Error: {error} - {error_description}"
                debug_print(f"[AUTHORIZED] {error_msg}")
                print(error_msg)
                return f"Login Error: {error} - {error_description}", 400 # Or render an error page

            code = request.args.get('code')
            if not code:
                error_msg = "Authorization code not found in callback."
                debug_print(f"[AUTHORIZED] {error_msg}")
                print(error_msg)
                return "Authorization code not found", 400

            # Build MSAL app WITH session cache (will be loaded by _build_msal_app via _load_cache)
            debug_print(f"[AUTHORIZED] Building MSAL app with cache...")
            msal_app = _build_msal_app(cache=_load_cache()) # Load existing cache
            debug_print(f"[AUTHORIZED] MSAL app built successfully")

            # Get settings from database, with environment variable fallback
            from functions_settings import get_settings
            settings = get_settings() or {}
            
            # Only use Front Door redirect URL if Front Door is enabled
            if settings.get('enable_front_door', False):
                front_door_url = settings.get('front_door_url')
                if front_door_url:
                    home_url, login_redirect_url = build_front_door_urls(front_door_url)
                    redirect_uri = login_redirect_url
                else:
                    # Fall back to environment variable if Front Door is enabled but no URL is set
                    redirect_uri = LOGIN_REDIRECT_URL or url_for('authorized', _external=True, _scheme='https')
            else:
                redirect_uri = url_for('authorized', _external=True, _scheme='https')
            
            debug_print(f"[AUTHORIZED] Token exchange using redirect_uri: {redirect_uri}")
            print(f"Token exchange using redirect_uri: {redirect_uri}")

            requested_scopes = get_requested_oauth_scopes(clear_after_read=True)
            debug_print(f"[AUTHORIZED] Requesting scopes: {requested_scopes}")
            debug_print(f"[AUTHORIZED] Calling acquire_token_by_authorization_code()...")
            
            result = msal_app.acquire_token_by_authorization_code(
                code=code,
                scopes=requested_scopes,
                redirect_uri=redirect_uri
            )
            debug_print(f"[AUTHORIZED] Token acquired successfully")

            if "error" in result:
                error_description = result.get("error_description", result.get("error"))
                error_msg = f"Token acquisition failure: {error_description}"
                debug_print(f"[AUTHORIZED] {error_msg}")
                print(error_msg)
                from functions_appinsights import log_event
                log_event("TOKEN_ACQUISITION_ERROR", {"error": error_description})
                return f"Login failure: {error_description}", 500

            # --- Store results ---
            # Store user identity info (claims from ID token)
            debug_print(f"[AUTHORIZED] [claims] User {result.get('id_token_claims', {}).get('name', 'Unknown')} logged in.")
            debug_print(f"[AUTHORIZED] [claims] User claims: {result.get('id_token_claims', {})}")

            session["user"] = result.get("id_token_claims")
            session["last_activity_epoch"] = int(time.time())

            # --- CRITICAL: Save the entire cache (contains tokens) to session ---
            _save_cache(msal_app.token_cache)

            print(f"User {session['user'].get('name')} logged in successfully.")
            
            # Log the login activity
            try:
                user_id = session['user'].get('oid') or session['user'].get('sub')
                if user_id:
                    log_user_login(user_id, 'azure_ad')
                    record_user_login_session_activity(session)
            except Exception as e:
                debug_print(f"Could not log login activity: {e}")
            
            # Redirect to the originally intended page or home
            # You might want to store the original destination in the session during /login
            # Get settings from database, with environment variable fallback
            from functions_settings import get_settings
            settings = get_settings() or {}
            
            debug_print(f"[AUTHORIZED] HOME_REDIRECT_URL (env): {HOME_REDIRECT_URL}")
            debug_print(f"[AUTHORIZED] front_door_url (db): {settings.get('front_door_url')}")
            debug_print(f"[AUTHORIZED] Front Door enabled: {settings.get('enable_front_door', False)}")

            # Only use Front Door redirect URL if Front Door is enabled
            if settings.get('enable_front_door', False):
                front_door_url = settings.get('front_door_url')
            if front_door_url:
                home_url, login_redirect_url = build_front_door_urls(front_door_url)
                print(f"Redirecting to configured Front Door URL: {home_url}")
                return redirect(home_url)
            elif HOME_REDIRECT_URL:
                # Fall back to environment variable if Front Door is enabled but no URL is set
                print(f"Redirecting to environment HOME_REDIRECT_URL: {HOME_REDIRECT_URL}")
                return redirect(HOME_REDIRECT_URL)
        
        debug_print(f"Front Door not enabled or URLs not set, falling back to url_for('index')")
        return redirect(url_for('index')) # Or another appropriate page
        
        except Exception as e:
            error_msg = f"Authorization callback failed: {str(e)}"
            debug_print(f"[AUTHORIZED] ERROR: {error_msg}")
            import traceback
            traceback.print_exc()
            debug_print(f"[AUTHORIZED] Full traceback:\n{traceback.format_exc()}")
            from functions_appinsights import log_event
            log_event("AUTHORIZED_ERROR", {"error": str(e), "type": type(e).__name__})
            return jsonify({"error": "Authentication failed", "message": error_msg}), 500

    # This route is for API calls that need a token, not the web app login flow. This does not kick off a session.
    @app.route('/getATokenApi') # This is your redirect URI path
    @swagger_route(security=get_auth_security())
    def authorized_api():
        # Check for errors passed back from Azure AD
        if request.args.get('error'):
            error = request.args.get('error')
            error_description = request.args.get('error_description', 'No description provided.')
            print(f"Azure AD Login Error: {error} - {error_description}")
            return f"Login Error: {error} - {error_description}", 400 # Or render an error page

        code = request.args.get('code')
        if not code:
            print("Authorization code not found in callback.")
            return "Authorization code not found", 400

        # Build MSAL app WITH session cache (will be loaded by _build_msal_app via _load_cache)
        msal_app = _build_msal_app(cache=_load_cache()) # Load existing cache

        # Get settings for redirect URI (same logic as other routes)
        from functions_settings import get_settings
        settings = get_settings() or {}
        
        if settings.get('enable_front_door', False):
            front_door_url = settings.get('front_door_url')
            if front_door_url:
                home_url, login_redirect_url = build_front_door_urls(front_door_url)
                redirect_uri = login_redirect_url
            else:
                redirect_uri = LOGIN_REDIRECT_URL or url_for('authorized', _external=True, _scheme='https')
        else:
            redirect_uri = url_for('authorized', _external=True, _scheme='https')

        requested_scopes = get_requested_oauth_scopes(clear_after_read=True)
        result = msal_app.acquire_token_by_authorization_code(
            code=code,
            scopes=requested_scopes,
            redirect_uri=redirect_uri
        )

        if "error" in result:
            error_description = result.get("error_description", result.get("error"))
            print(f"Token acquisition failure: {error_description}")
            return f"Login failure: {error_description}", 500

        return jsonify(result, 200)

    @app.route('/logout/local')
    @swagger_route(security=get_auth_security())
    def local_logout():
        """
        Clear the local Flask session and redirect to the configured home destination.

        Args:
            None.

        Returns:
            Response: A redirect response to the local or Front Door home URL.
        Raises:
            None.
        """
        session.clear()

        from functions_settings import get_settings
        settings = get_settings() or {}

        if settings.get('enable_front_door', False):
            front_door_url = settings.get('front_door_url')
            if front_door_url:
                home_url, _ = build_front_door_urls(front_door_url)
                logout_uri = home_url
            elif HOME_REDIRECT_URL:
                logout_uri = HOME_REDIRECT_URL
            else:
                logout_uri = url_for('index')
        else:
            logout_uri = url_for('index')

        return redirect(logout_uri)

    @app.route('/logout')
    @swagger_route(security=get_auth_security())
    def logout():
        user_name = session.get("user", {}).get("name", "User")
        # Get the user's email before clearing the session
        user_email = session.get("user", {}).get("preferred_username") or session.get("user", {}).get("email")
        # Clear Flask session data
        session.clear()
        # Redirect user to Azure AD logout endpoint
        # MSAL provides a helper for this too, but constructing manually is fine
        # Get settings from database, with environment variable fallback
        from functions_settings import get_settings
        settings = get_settings() or {}
        
        # Only use Front Door redirect URL if Front Door is enabled
        if settings.get('enable_front_door', False):
            front_door_url = settings.get('front_door_url')
            if front_door_url:
                home_url, login_redirect_url = build_front_door_urls(front_door_url)
                logout_uri = home_url
            elif HOME_REDIRECT_URL:
                # Fall back to environment variable if Front Door is enabled but no URL is set
                logout_uri = HOME_REDIRECT_URL
            else:
                logout_uri = url_for('index', _external=True)
        else:
            logout_uri = url_for('index', _external=True)
        
        debug_print(f"Front Door enabled: {settings.get('enable_front_door', False)}")
        debug_print(f"Front Door URL: {settings.get('front_door_url')}")
        debug_print(f"Logout redirect URI: {logout_uri}")
        
        logout_url = (
            f"{AUTHORITY}/oauth2/v2.0/logout"
            f"?post_logout_redirect_uri={quote(logout_uri)}"
        )
        # Add logout_hint parameter if we have the user's email
        if user_email:
            logout_url += f"&logout_hint={quote(user_email)}"
        
        debug_print(f"{user_name} logged out. Redirecting to Azure AD logout.")
        return redirect(logout_url)