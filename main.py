import os
import io
import tempfile
import subprocess
from pathlib import Path
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PyPDF2 import PdfWriter, PdfReader
from PIL import Image


user_data = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    commands = [
        "📄 <b>Основные команды:</b>",
        "/start - Показать это меню",
        "/newpdf - Создать новый PDF документ",
        "/cancel - Отменить текущее создание PDF",
        "",
        "📌 <b>При создании PDF:</b>",
        "/done - Завершить добавление изображений",
        "",
        "🖼 <b>Как использовать:</b>",
        "1. Начните с /newpdf",
        "2. Отправьте текст (будет отцентрирован)",
        "3. Отправьте одно или несколько изображений",
        "4. Завершите командой /done",
        "",
        "ℹ Изображения будут добавлены под текстом в порядке получения"
    ]

    await update.message.reply_text(
        "\n".join(commands),
        parse_mode="HTML"
    )


async def new_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat.id
    user_data[chat_id] = {
        "step": "waiting_text",
        "text": None,
        "images": [],
        "processing": False
    }
    await update.message.reply_text(
        "✍ Отправьте текст для PDF (будет отцентрирован на странице):\n\n"
        "🖼 После текста можно добавить изображения (они будут размещены под текстом)\n\n"
        "❌ /cancel - отменить создание"
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat.id

    if chat_id not in user_data or user_data[chat_id]["step"] != "waiting_text":
        return

    user_data[chat_id]["text"] = update.message.text
    user_data[chat_id]["step"] = "waiting_images"

    await update.message.reply_text(
        "✅ Текст получен и будет отцентрирован в PDF.\n\n"
        "🖼 Теперь можно отправить одно или несколько изображений "
        "(они будут добавлены под текстом в порядке получения).\n\n"
        "⏩ /done - завершить и создать PDF\n"
        "❌ /cancel - отменить"
    )


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #обработка полученных изображений
    chat_id = update.message.chat.id

    if chat_id not in user_data or user_data[chat_id]["step"] != "waiting_images":
        return

    try:
        photo_file = await update.message.photo[-1].get_file()
        image_path = f"tmp_{chat_id}_{len(user_data[chat_id]['images'])}.jpg"
        await photo_file.download_to_drive(image_path)

        user_data[chat_id]["images"].append(image_path)

        await update.message.reply_text(
            f"✅ Изображение {len(user_data[chat_id]['images'])} добавлено.\n"
            "Можно отправить еще или /done для создания PDF"
        )
    except Exception as e:
        await update.message.reply_text(f"⚠ Ошибка: {str(e)}")


async def done_images(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat.id

    if chat_id not in user_data or user_data[chat_id].get("processing"):
        return

    user_data[chat_id]["processing"] = True
    await update.message.reply_text("⏳ Создаю PDF...")

    pdf_path = f"result_{chat_id}.pdf"
    success = create_centered_pdf(
        text=user_data[chat_id]["text"],
        image_paths=user_data[chat_id]["images"],
        output_path=pdf_path
    )

    if success:
        await send_result(update, pdf_path, chat_id)
    else:
        await update.message.reply_text("⚠ Ошибка при создании PDF")
        cleanup_files(pdf_path, *user_data[chat_id]["images"])
        del user_data[chat_id]


def create_centered_pdf(text: str, image_paths: list, output_path: str) -> bool:
    """
    Создает PDF с центрированным текстом и изображениями под ним

    :param text: Текст (будет отцентрирован)
    :param image_paths: Список путей к изображениям (будут под текстом)
    :param output_path: Путь для сохранения PDF
    :return: True если успешно, иначе False
    """
    try:
        # Регистрируем шрифт
        try:
            pdfmetrics.registerFont(TTFont('ArialUnicode', 'arial.ttf'))
            font_name = 'ArialUnicode'
        except:
            font_name = 'Helvetica'

        output = PdfWriter()
        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=letter)
        page_width, page_height = letter

        # Добавляем отцентрированный текст в верхней части страницы
        if text:
            can.setFont(font_name, 12)
            text_lines = text.split('\n')
            y_position = page_height - 100  # Начальная позиция текста

            for line in text_lines:
                line = line.strip()
                if line:  # Пропускаем пустые строки
                    text_width = can.stringWidth(line, font_name, 12)
                    x_position = (page_width - text_width) / 2
                    can.drawString(x_position, y_position, line)
                    y_position -= 20  # Межстрочный интервал

        # Добавляем изображения под текстом
        current_y = y_position - 50  # Отступ от текста до первого изображения

        for img_path in image_paths:
            if os.path.exists(img_path):
                img = Image.open(img_path)
                img_width, img_height = img.size

                # Масштабируем изображение, чтобы оно вмещалось на странице
                max_width = page_width - 100
                max_height = (current_y - 50) if (current_y - 50) > 0 else page_height / 2

                scale_factor = min(
                    max_width / img_width,
                    max_height / img_height
                )

                scaled_width = img_width * scale_factor
                scaled_height = img_height * scale_factor

                # Позиционируем по центру и с отступом от текста/предыдущего изображения
                x_pos = (page_width - scaled_width) / 2
                current_y -= scaled_height  # Обновляем текущую позицию по Y

                if current_y < 50:  # Если не хватает места - создаем новую страницу
                    can.save()
                    packet.seek(0)
                    output.add_page(PdfReader(packet).pages[0])

                    # Создаем новую страницу
                    packet = io.BytesIO()
                    can = canvas.Canvas(packet, pagesize=letter)
                    current_y = page_height - scaled_height - 50
                    x_pos = (page_width - scaled_width) / 2

                can.drawImage(
                    img_path,
                    x_pos, current_y,
                    width=scaled_width,
                    height=scaled_height,
                    preserveAspectRatio=True
                )

                current_y -= 30  # Отступ между изображениями

        can.save()
        packet.seek(0)
        output.add_page(PdfReader(packet).pages[0])

        with open(output_path, "wb") as f:
            output.write(f)

        return True
    except Exception as e:
        print(f"Ошибка создания PDF: {e}")
        return False


async def send_result(update: Update, pdf_path: str, chat_id: int) -> None:
    """Отправляет готовый PDF и очищает временные файлы"""
    try:
        with open(pdf_path, "rb") as pdf_file:
            await update.message.reply_document(
                document=pdf_file,
                caption="✅ Ваш PDF готов!\n\n"
                        "Текст отцентрирован, изображения добавлены под ним."
            )
    except Exception as e:
        await update.message.reply_text(f"⚠ Ошибка отправки: {str(e)}")
    finally:
        if chat_id in user_data:
            cleanup_files(pdf_path, *user_data[chat_id]["images"])
            del user_data[chat_id]


def cleanup_files(*file_paths) -> None:
    """Удаляет временные файлы"""
    for path in file_paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception as e:
            print(f"Ошибка удаления {path}: {e}")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отменяет текущее создание PDF"""
    chat_id = update.message.chat.id
    if chat_id in user_data:
        cleanup_files(
            f"result_{chat_id}.pdf",
            *user_data[chat_id].get("images", [])
        )
        del user_data[chat_id]
        await update.message.reply_text("❌ Создание PDF отменено")
    else:
        await update.message.reply_text("ℹ Нет активного процесса создания")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает ошибки"""
    await update.message.reply_text(
        "⚠ Произошла ошибка. Попробуйте снова /newpdf\n\n"
        "Если проблема повторяется, используйте /cancel и начните заново."
    )
    print(f"Ошибка: {context.error}")



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    commands = [
        "📄 <b>Основные команды:</b>",
        "/start - Показать это меню",
        "/newpdf - Создать новый PDF из текста и изображений",
        "/convert - Конвертировать файл (DOCX, PPTX, TXT) в PDF",
        "/cancel - Отменить текущую операцию",
        "",
        "📌 <b>При создании PDF:</b>",
        "/done - Завершить добавление изображений",
        "",
        "🖼 <b>Поддерживаемые форматы для /convert:</b>",
        "• DOC/DOCX (Word документ)",
        "• PPTX (PowerPoint презентация)",
        "• TXT (Текстовый файл)"
    ]

    await update.message.reply_text(
        "\n".join(commands),
        parse_mode="HTML"
    )


async def convert_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat.id
    user_data[chat_id] = {
        "mode": "waiting_conversion_file",
        "processing": False
    }

    await update.message.reply_text(
        "🔄 Отправьте файл для конвертации в PDF (поддерживаются DOCX, PPTX, TXT):\n\n"
        "❌ /cancel - отменить операцию"
    )


async def handle_conversion_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает файл для конвертации"""
    chat_id = update.message.chat.id

    if chat_id not in user_data or user_data[chat_id].get("mode") != "waiting_conversion_file":
        return

    if not update.message.document:
        await update.message.reply_text("⚠ Пожалуйста, отправьте файл")
        return

    document = update.message.document
    file_ext = Path(document.file_name).suffix.lower()

    if file_ext not in ('.doc', '.docx', '.pptx', '.txt'):
        await update.message.reply_text(
            "⚠ Поддерживаются только:\n"
            "• .doc/.docx\n• .pptx\n• .txt\n\n"
            "Для создания PDF из изображений используйте /newpdf"
        )
        del user_data[chat_id]
        return

    user_data[chat_id]["processing"] = True
    await update.message.reply_text("⏳ Конвертирую файл...")

    try:
        # Скачиваем временный файл
        file = await document.get_file()
        input_path = f"convert_input_{chat_id}{file_ext}"
        await file.download_to_drive(input_path)

        # Конвертируем в PDF
        output_path = f"converted_{chat_id}.pdf"

        if file_ext == '.txt':
            success = await simple_txt_to_pdf(input_path, output_path)
        else:
            success = convert_via_libreoffice(input_path, output_path)

        if success:
            with open(output_path, 'rb') as pdf_file:
                await update.message.reply_document(
                    document=pdf_file,
                    caption=f"✅ Файл конвертирован в PDF: {document.file_name}"
                )
        else:
            await update.message.reply_text("⚠ Не удалось конвертировать файл")

    except Exception as e:
        await update.message.reply_text(f"⚠ Ошибка: {str(e)}")
    finally:
        # Очистка временных файлов
        if 'input_path' in locals() and os.path.exists(input_path):
            os.remove(input_path)
        if 'output_path' in locals() and os.path.exists(output_path):
            os.remove(output_path)
        if chat_id in user_data:
            del user_data[chat_id]


async def simple_txt_to_pdf(input_path: str, output_path: str) -> bool:
    """Конвертация TXT в PDF"""
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            text = f.read()

        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=letter)

        try:
            pdfmetrics.registerFont(TTFont('ArialUnicode', 'arial.ttf'))
            font_name = 'ArialUnicode'
        except:
            font_name = 'Helvetica'

        can.setFont(font_name, 12)
        text_obj = can.beginText(40, 750)

        for line in text.split('\n'):
            text_obj.textLine(line.strip())

        can.drawText(text_obj)
        can.save()

        packet.seek(0)
        new_pdf_page = PdfReader(packet).pages[0]
        output = PdfWriter()
        output.add_page(new_pdf_page)

        with open(output_path, "wb") as f:
            output.write(f)

        return True
    except Exception as e:
        print(f"Ошибка конвертации TXT: {e}")
        return False


def convert_via_libreoffice(input_path: str, output_path: str) -> bool:
    """
    Конвертация файлов в PDF через LibreOffice

    :param input_path: Путь к исходному файлу
    :param output_path: Путь для сохранения PDF
    :return: True если успешно, иначе False
    """
    try:
        libreoffice_path = find_libreoffice()
        if not libreoffice_path:
            print("LibreOffice не найден!")
            return False

        # Создаем выходную директорию если нужно
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        cmd = [
            libreoffice_path,
            '--headless',
            '--convert-to', 'pdf',
            '--outdir', output_dir,
            input_path
        ]

        result = subprocess.run(cmd, check=True, capture_output=True)

        if result.returncode == 0:
            # LibreOffice сохраняет файл с таким же именем но .pdf расширением
            expected_path = os.path.join(
                output_dir,
                f"{Path(input_path).stem}.pdf"
            )

            if os.path.exists(expected_path):
                # Если путь не совпадает с ожидаемым, переименовываем
                if expected_path != output_path:
                    os.rename(expected_path, output_path)
                return True

        print(f"Ошибка конвертации LibreOffice: {result.stderr.decode()}")
        return False

    except subprocess.CalledProcessError as e:
        print(f"LibreOffice ошибка: {e.stderr.decode()}")
    except Exception as e:
        print(f"Неожиданная ошибка: {e}")

    return False


def find_libreoffice() -> str:
    """Поиск пути к LibreOffice в различных ОС"""
    paths = [
        'C:\\Program Files\\LibreOffice\\program\\soffice.exe',
        '/Applications/LibreOffice.app/Contents/MacOS/soffice',
    ]

    for path in paths:
        if os.path.exists(path):
            return path

    # Пробуем найти в PATH
    try:
        libre_path = subprocess.check_output(['which', 'libreoffice']).decode().strip()
        if libre_path:
            return libre_path
    except:
        pass

    try:
        soffice_path = subprocess.check_output(['which', 'soffice']).decode().strip()
        if soffice_path:
            return soffice_path
    except:
        pass

    return None

def main() -> None:
    application = Application.builder().token("8063676245:AAHDmoeUUw7cxxgTCybeGV6hJjSZvA7PNcY").build()

    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("newpdf", new_pdf))
    application.add_handler(CommandHandler("convert", convert_command))
    application.add_handler(CommandHandler("done", done_images))
    application.add_handler(CommandHandler("cancel", cancel))

    # Обработчики сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, handle_conversion_file))

    # Ошибки
    application.add_error_handler(error_handler)

    print("Бот запущен...")
    application.run_polling()


if __name__ == "__main__":
    main()


