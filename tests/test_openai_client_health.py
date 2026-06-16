def test_openai_client_imports():
    import openai

    openai.OpenAI(api_key="x", base_url="http://127.0.0.1:1/v1")
