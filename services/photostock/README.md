# PhotoStock Service

FastAPI-сервис выдачи изображений из S3/MinIO bucket `images`.

Сервис ищет файл по **базовому имени без расширения** и возвращает бинарный контент изображения.

## Endpoint

### `GET /images/{image}?display=<true|false>`

- `image`: имя изображения **без расширения**
  - допустимые символы: `A-Z`, `a-z`, `0-9`, `_`, `-`
  - запрещены пути (`/`, `\`), абсолютные пути, `.` и `..`, расширение
- `display` (optional):
  - `true` / `1` / `yes` -> `inline`
  - `false` / `0` / `no` -> `attachment`
  - по умолчанию: `inline`

Поддерживаемые расширения в S3:

- `.jpg`
- `.jpeg`
- `.png`
- `.gif`
- `.webp`

## Поведение поиска

Для `image=cat` сервис ищет объекты с префиксом `cat.` и фильтрует только поддерживаемые расширения.

- если найден ровно один файл -> возвращает его
- если не найдено ни одного -> `404 Image not found`
- если найдено несколько (`cat.jpg` и `cat.webp`) -> `409 Multiple files found ...`

## Ответ при успехе (`200`)

- body: bytes (изображение)
- `Content-Type`: из `S3 ContentType` или по расширению файла
- `Content-Disposition`:
  - `inline; filename="..."` (по умолчанию)
  - `attachment; filename="..."` (если `display=false`)
- `Cache-Control: public, max-age=3600`

## Ошибки

- `400`:
  - невалидный `image` (содержит расширение, путь или недопустимые символы)
  - невалидный `display`
- `404`:
  - изображение не найдено
- `409`:
  - найдено несколько файлов для одного base name
- `503`:
  - ошибка доступа к S3/MinIO

Формат ошибок FastAPI:

```json
{
  "detail": "..."
}
```

## ENV

- `S3_ENDPOINT` (default: `http://s3:9000`)
- `S3_ACCESS_KEY` (default: `dev`)
- `S3_SECRET_KEY` (default: `devpassword`)
- `S3_BUCKET` (default: `images`)
- `S3_REGION` (default: `us-east-1`)
- `S3_USE_SSL` (default: `false`)
- `S3_FORCE_PATH_STYLE` (default: `true`)

## Примеры

Inline (по умолчанию):

```bash
curl -i "http://localhost:8000/images/cat"
```

Attachment:

```bash
curl -i "http://localhost:8000/images/cat?display=false"
```

Невалидный параметр:

```bash
curl -i "http://localhost:8000/images/cat.png"
```

## Интеграция с другими сервисами

- `moments` хранит `images` как filename (например, `IMG_001.jpg`)
- для `photostock` нужно передавать basename: `IMG_001`
- итоговый URL: `/images/IMG_001`

## Auth / CORS

- Авторизация не требуется
- CORS middleware в сервисе не настроен
