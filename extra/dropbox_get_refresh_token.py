# tools/extra/dropbox_get_refresh_token.py
import os
from dropbox import DropboxOAuth2FlowNoRedirect
APP_KEY = os.environ.get("DROPBOX_APP_KEY") or input("APP_KEY: ").strip()
APP_SECRET = os.environ.get("DROPBOX_APP_SECRET") or input("APP_SECRET: ").strip()
# Be om offline-tilgang (gir refresh token)
auth_flow = DropboxOAuth2FlowNoRedirect(
    APP_KEY,
    APP_SECRET,
    token_access_type="offline",  # <- viktig
    use_pkce=True,  # <- PKCE
)
authorize_url = auth_flow.start()
print("\n1) Åpne i nettleser og godkjenn:\n", authorize_url)
print("2) Lim inn koden her:\n")
auth_code = input("CODE: ").strip()
oauth_result = auth_flow.finish(auth_code)
print("\nOK!")
print("ACCESS_TOKEN (kortlivet):", oauth_result.access_token)
print("REFRESH_TOKEN:", oauth_result.refresh_token)
print("ACCOUNT_ID:", oauth_result.account_id)
