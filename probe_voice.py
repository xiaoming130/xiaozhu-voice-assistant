import pyttsx3
engine = pyttsx3.init()
voices = engine.getProperty('voices')
print("total:", len(voices))
for v in voices:
    langs = []
    try:
        langs = [str(l) for l in (v.languages or [])]
    except Exception:
        pass
    print("-", v.id)
    print("   name:", v.name)
    print("   langs:", langs)
