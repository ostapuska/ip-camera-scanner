# IP Camera Scanner

Система для автоматизованого виявлення, автентифікації та взаємодії з IP-камерами в локальній мережі.

## Можливості

- Автоматичне сканування мережі для виявлення IP-камер
- Визначення виробника камери (Hikvision, Dahua, Axis, DLink, Foscam та інші)
- Підбір облікових даних для автентифікації
- Пошук URL для доступу до фото та відеопотоків
- Перегляд потоків з камер у реальному часі
- Запис відео та знімків
- Інтеграція з Telegram для віддаленого моніторингу

## Вимоги

- Python 3.8+
- nmap
- ffmpeg
- Network Manager (для Linux)
- Додаткові бібліотеки Python (див. requirements.txt)

## Встановлення

```bash
# Клонування репозиторію
git clone https://github.com/YOUR_USERNAME/ip-camera-scanner.git
cd ip-camera-scanner

# Встановлення залежностей
pip install -r requirements.txt

# Встановлення системних залежностей (Linux)
sudo apt install nmap ffmpeg network-manager
```

## Використання

```bash
python codev_1.py
```

## Структура проекту

- `codev_1.py` - основний файл програми
- `requirements.txt` - залежності проекту
- `README.md` - документація
- `LICENSE` - ліцензія MIT

## Автор

Ostap камернік

## Ліцензія

MIT License