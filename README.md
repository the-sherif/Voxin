# Voxin

Голосовой ввод для Linux с офлайн-распознаванием речи. Открываешь окно, нажимаешь кнопку или хоткей — говоришь — текст появляется в окне и копируется в буфер обмена.

## Возможности

- Офлайн-распознавание через [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- Глобальный хоткей `Ctrl+Shift+Space` работает на Wayland и X11
- PyQt6 UI: всегда поверх других окон, поле с текстом, кнопки «Копировать» и «Очистить»
- Автокопирование результата в буфер обмена

## Требования

- Python 3.10+
- KDE Plasma / любой DE на Wayland или X11
- Пользователь в группе `input` (для глобального хоткея)
- Системные пакеты:

```bash
# Fedora
sudo dnf install wl-clipboard python3-pyaudio portaudio-devel

# Ubuntu/Debian
sudo apt install wl-clipboard python3-pyaudio portaudio19-dev
```

Добавить пользователя в группу `input` (нужен перелогин):

```bash
sudo usermod -aG input $USER
```

## Установка

```bash
git clone https://github.com/the-sherif/Voxin.git
cd Voxin

python -m venv venv
source venv/bin/activate

pip install faster-whisper pyaudio evdev PyQt6
```

## Запуск

```bash
source venv/bin/activate
python main.py
```

При первом запуске модель Whisper скачается автоматически (~150 МБ).

## Использование

| Действие | Результат |
|---|---|
| Кнопка **Начать запись** или `Ctrl+Shift+Space` | Начать запись |
| Кнопка **Стоп** или `Ctrl+Shift+Space` повторно | Остановить и распознать |
| `Ctrl+V` в любом приложении | Вставить распознанный текст |

## Структура проекта

```
Voxin/
├── main.py          # UI и логика записи
├── transcriber.py   # worker-процесс с faster-whisper
└── toggle.py        # резервный триггер через UNIX-сигнал
```

## Модели Whisper

По умолчанию используется модель `base`. Можно изменить в `transcriber.py`:

| Модель | Размер | Точность | Скорость |
|---|---|---|---|
| `tiny` | 75 МБ | низкая | очень быстро |
| `base` | 150 МБ | средняя | быстро |
| `small` | 500 МБ | хорошая | средне |
| `medium` | 1.5 ГБ | высокая | медленно |
| `large` | 3 ГБ | лучшая | очень медленно |
