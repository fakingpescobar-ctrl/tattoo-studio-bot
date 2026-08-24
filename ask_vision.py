"""
Локальная vision-модель через Ollama API.

Использование:
    python ask_vision.py <путь_к_скриншоту> [вопрос]

Пример:
    python ask_vision.py screenshot.png "Опиши что видишь на скриншоте"

Модель по умолчанию: gemma3:4b (vision).
"""
import base64
import json
import sys
import urllib.request
import urllib.error

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "gemma3:4b"


def ask_vision(image_path, question="Опиши подробно что ты видишь на этом скриншоте.",
               model=DEFAULT_MODEL):
    """Отправляет изображение + вопрос в локальную Ollama vision-модель."""
    # Читаем картинку → base64
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": question,
                "images": [image_b64],
            }
        ],
        "stream": False,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=data,
        headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["message"]["content"]
    except urllib.error.URLError as e:
        return f"[ERROR] Ollama не запущена? {e}"
    except KeyError:
        return f"[ERROR] Неожиданный ответ: {result}"
    except Exception as e:
        return f"[ERROR] {e}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python ask_vision.py <скриншот> [вопрос]")
        print(f"Модель по умолчанию: {DEFAULT_MODEL}")
        sys.exit(1)

    img = sys.argv[1]
    q = sys.argv[2] if len(sys.argv) > 2 else \
        "Опиши подробно что ты видишь на этом скриншоте. Обрати внимание на цвета, рамки, разделители, текст."

    print(f"Модель: {DEFAULT_MODEL}")
    print(f"Картинка: {img}")
    print(f"Вопрос: {q}")
    print("---")
    answer = ask_vision(img, q)
    print(answer)
