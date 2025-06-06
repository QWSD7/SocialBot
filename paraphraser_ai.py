import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from razdel import sentenize
import re

MODEL_NAME = "cointegrated/rut5-base-paraphraser"

print("Загружаем модель и токенизатор...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model.to(device)
model.eval()


def paraphrase_rut5(text: str, max_length: int = 300) -> str:
    # input_text = f"перефразируй текст и сократи его: {text}"
    input_text = text
    inputs = tokenizer.encode(
        input_text, return_tensors="pt", max_length=512, truncation=True
    ).to(device)

    with torch.no_grad():
        output_ids = model.generate(
            inputs,
            max_length=max_length,
            num_beams=5,
            do_sample=True,
            top_p=0.95,
            top_k=50,
            temperature=0.9,
            no_repeat_ngram_size=3,
            early_stopping=True,
        )

    return tokenizer.decode(output_ids[0], skip_special_tokens=True)


def clean_input(text: str) -> str:
    text = text.replace('"""', "").replace("“", "").replace("”", "")
    text = re.sub(r'(?<!\w)"(.*?)"(?!\w)', r"\1", text)
    return text.strip()


def paraphrase_long_text(text: str, max_total_len: int = 900) -> str:
    sentences = [s.text for s in sentenize(text)]
    blocks = []
    block = ""
    for s in sentences:
        if len(block + " " + s) < 400:  # собираем блоки по ~3 предложения
            block += " " + s
        else:
            blocks.append(block.strip())
            block = s
    if block:
        blocks.append(block.strip())

    paraphrased = []
    for block in blocks:
        paraphrased_block = paraphrase_rut5(block)
        cleaned = clean_input(paraphrased_block)
        paraphrased.append(cleaned)

        if len(" ".join(paraphrased)) > max_total_len:
            break

    final_text = " ".join(paraphrased)
    return trim_to_nearest_sentence(final_text, max_total_len)


def trim_to_nearest_sentence(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    trimmed = text[:max_len]
    last_dot = trimmed.rfind(".")
    if last_dot != -1 and last_dot > max_len * 0.6:
        return trimmed[: last_dot + 1]
    return trimmed.strip()


# if __name__ == "__main__":
#     print("Введите текст для перефразирования:")
#     input_text = input("> ")

#     if not input_text.strip():
#         print("Ошибка: пустой ввод.")
#     else:
#         result = paraphrase_long_text(input_text)
#         print("\n🔁 Перефразированный текст (до 900 символов):\n")
#         print(result)
