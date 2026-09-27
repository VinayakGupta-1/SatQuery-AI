"""SatQuery AI backend."""

#: The service version, reported by the API and in /capabilities.
__version__ = "1.1.0"

#: Sent with every outbound request. Hosted endpoints behind Cloudflare, Groq
#: among them, refuse Python's default "Python-urllib" agent with HTTP 403
#: (error 1010) before the API key is even read.
USER_AGENT = f"SatQuery/{__version__}"
