# Plan de Desarrollo — App de Sugerencias de Movies/Series (Amigos & Familia)

## 1. Objetivo

Web app privada donde un grupo cerrado de amigos/familia, invitados por link, puede:
- Sugerir películas/series (con imagen e info de TMDB).
- Ver las sugerencias del resto.
- Llevar su propia watchlist (pendiente/vista).
- Comentar sugerencias.

## 2. Alcance v1

**Incluido:**
- Registro vía link de invitación (email + password).
- Feed de sugerencias (propias y ajenas).
- Alta de sugerencia con buscador TMDB (autocompletado por título, trae poster + info).
- Watchlist personal por usuario (pendiente / vista).
- Comentarios en cada sugerencia.
- Roles: `user`, `admin`, `superadmin`.
- Panel simple de admin para generar links de invitación, con mensaje pre-armado listo para copiar/enviar por WhatsApp o email.
- Settings: inicializar o resetear la base de datos (superadmin).
- Activity log de acciones relevantes del sistema.

**Fuera de alcance v1 (backlog v2):**
- Votos/ratings sobre sugerencias.
- Notificaciones (email/WhatsApp) de nuevas sugerencias.
- Filtros avanzados (género, plataforma de streaming, año).
- Exportar catálogo/watchlist a Excel (aunque `openpyxl` ya está en el stack, se deja para v2 si hace falta).

## 3. Roles y Permisos

| Rol | Puede |
|---|---|
| `user` | Sugerir, comentar, gestionar su watchlist |
| `admin` | Todo lo de `user` + generar/ver links de invitación, moderar (borrar) sugerencias/comentarios ajenos, ver activity log |
| `superadmin` | Todo lo de `admin` + gestionar roles de otros usuarios + inicializar/resetear la base de datos |

El primer `superadmin` se crea manualmente (seed script o inserción directa), ya que no hay lista previa de emails.

## 4. Flujo de Invitación y Registro

1. Un `admin`/`superadmin` genera un link de invitación desde `/admin/invitations` (token único, con expiración configurable, ej. 7 días).
2. La pantalla de invitaciones muestra, junto al link, dos atajos de conveniencia para compartirlo tal cual está, sin pasar por servidor propio ni API de WhatsApp:
   - Botón "Enviar por WhatsApp" → abre `https://wa.me/?text={mensaje + link}` con el texto pre-armado.
   - Botón "Enviar por email" → abre `mailto:?subject=...&body={mensaje + link}` con el cliente de correo del usuario.
   Vos elegís el destinatario final en WhatsApp o en el mail que se abre; no hay envío automático ni se guardan destinatarios.
3. El invitado abre `/register/{token}`:
   - Si el token es válido y no fue usado → formulario de registro (email + password).
   - Si expiró o ya fue usado → mensaje de error, sin acceso.
4. Al registrarse, se marca el token como usado (`used_by`, `used_at`) y se loguea automáticamente.
5. Login normal después vía `/login` (email + password → cookie de sesión firmada).

Nota: como no tenés los emails de todos de antemano, el token de invitación **no** está atado a un email específico — cualquiera con el link puede registrarse mientras el token esté vigente y sin usar. Si en el futuro querés invitaciones nominales (1 token = 1 email específico), es un cambio menor al modelo (agregar `email` obligatorio en `invitations`).

## 5. Modelo de Datos (PostgreSQL / SQLAlchemy)

### `users`
| Campo | Tipo | Notas |
|---|---|---|
| id | PK, int | |
| email | str, unique | |
| password_hash | str | bcrypt vía `passlib` |
| display_name | str | |
| role | enum(`user`,`admin`,`superadmin`) | default `user` |
| invited_by | FK → users.id, nullable | quién generó la invitación usada |
| created_at | datetime | |

### `invitations`
| Campo | Tipo | Notas |
|---|---|---|
| id | PK, int | |
| token | str, unique, indexado | uuid4 o similar, no adivinable |
| created_by | FK → users.id | |
| used_by | FK → users.id, nullable | |
| used_at | datetime, nullable | |
| expires_at | datetime | |
| created_at | datetime | |

### `suggestions`
| Campo | Tipo | Notas |
|---|---|---|
| id | PK, int | |
| tmdb_id | int | id de TMDB |
| media_type | enum(`movie`,`tv`) | |
| title | str | cacheado desde TMDB |
| poster_path | str, nullable | cacheado desde TMDB |
| overview | text, nullable | cacheado desde TMDB |
| release_date | date, nullable | cacheado desde TMDB |
| suggested_by | FK → users.id | |
| created_at | datetime | |

### `watchlist_entries`
| Campo | Tipo | Notas |
|---|---|---|
| id | PK, int | |
| user_id | FK → users.id | |
| suggestion_id | FK → suggestions.id | |
| status | enum(`pending`,`watched`) | default `pending` |
| updated_at | datetime | |

Constraint: único por (`user_id`, `suggestion_id`).

### `comments`
| Campo | Tipo | Notas |
|---|---|---|
| id | PK, int | |
| suggestion_id | FK → suggestions.id | |
| user_id | FK → users.id | |
| body | text | |
| created_at | datetime | |

### `activity_log`
| Campo | Tipo | Notas |
|---|---|---|
| id | PK, int | |
| user_id | FK → users.id, nullable | null para acciones de sistema (ej. reset de DB) |
| action | str/enum | `user_registered`, `user_login`, `suggestion_created`, `comment_created`, `watchlist_updated`, `invitation_created`, `invitation_used`, `role_changed`, `db_initialized`, `db_reset` |
| target_type | str, nullable | ej. `suggestion`, `user`, `invitation` |
| target_id | int, nullable | id del objeto afectado |
| detail | text/JSON, nullable | info adicional legible (ej. rol anterior → nuevo) |
| created_at | datetime | |

Se recomienda un helper simple (`log_activity(db, user_id, action, ...)`) llamado desde cada endpoint relevante, en vez de lógica dispersa.

**Relaciones:** un `user` tiene muchas `suggestions`, muchos `watchlist_entries`, muchos `comments` y muchas `activity_log` entries. Una `suggestion` tiene muchos `comments` y muchos `watchlist_entries` (uno por usuario que la agregó a su lista).

## 6. Integración con TMDB

- **Búsqueda al crear sugerencia:** `GET /search/multi` (o `/search/movie` + `/search/tv` si querés separarlos) — autocompletado mientras el usuario escribe el título.
- **Detalle al confirmar:** `GET /movie/{id}` o `GET /tv/{id}` para traer `overview`, `release_date`, `poster_path` completos y guardarlos cacheados en `suggestions` (evita depender de TMDB para mostrar el feed después, y protege ante rate limits).
- **Imágenes:** se arman con `https://image.tmdb.org/t/p/w500{poster_path}`.
- **Config:** `TMDB_API_KEY` como variable de entorno, nunca hardcodeada. Un cliente HTTP simple (ej. `httpx`) con timeout corto y manejo de error si TMDB no responde (no debería tumbar el alta de sugerencia, solo degradar sin imagen).

## 7. Rutas / Vistas (Jinja2, server-side)

| Ruta | Método | Descripción |
|---|---|---|
| `/login` | GET/POST | Login |
| `/logout` | POST | Cierra sesión |
| `/register/{token}` | GET/POST | Registro vía invitación |
| `/` | GET | Feed de sugerencias |
| `/suggestions/new` | GET/POST | Buscador TMDB + alta de sugerencia |
| `/suggestions/{id}` | GET | Detalle + comentarios |
| `/suggestions/{id}/comments` | POST | Nuevo comentario |
| `/watchlist` | GET | Mi watchlist |
| `/watchlist/{suggestion_id}` | POST | Agregar/actualizar estado en mi watchlist |
| `/admin/invitations` | GET/POST | Generar y listar links, con atajos WhatsApp/email (admin+) |
| `/admin/users` | GET/POST | Gestión de roles (superadmin) |
| `/admin/settings` | GET/POST | Inicializar o resetear la DB (superadmin) |
| `/admin/activity-log` | GET | Ver historial de actividad (admin+) |

## 8. Estructura de Carpetas Sugerida

```
app/
  main.py
  config.py                # env vars (DB URL, TMDB_API_KEY, SECRET_KEY)
  db.py                     # engine, get_db context manager
  models/
    user.py
    invitation.py
    suggestion.py
    watchlist.py
    comment.py
    activity_log.py
  routers/
    auth.py
    suggestions.py
    watchlist.py
    admin.py                # invitations, users, settings, activity-log
  services/
    tmdb.py                 # cliente TMDB
    auth.py                 # hashing, cookies firmadas, dependencias de sesión/rol
    activity_log.py         # helper log_activity(...)
  templates/
    base.html
    login.html
    register.html
    feed.html
    suggestion_detail.html
    suggestion_new.html
    watchlist.html
    admin_invitations.html
    admin_users.html
    admin_settings.html
    admin_activity_log.html
  static/
alembic/                    # migraciones (recomendado dado que usás SQLAlchemy + Postgres)
```

## 9. Consideraciones Técnicas

- **Sesiones:** cookie firmada con `itsdangerous`, conteniendo `user_id` (o similar), con expiración razonable (ej. 30 días) y flag `httponly`.
- **Passwords:** hashear con `passlib[bcrypt]`, nunca texto plano ni hash propio.
- **Autorización:** dependencias de FastAPI (`Depends`) que validan sesión y rol antes de rutas de admin.
- **Migraciones:** con Postgres real (no SQLite), conviene sumar Alembic desde el día 1 para no pelear con cambios de esquema más adelante.
- **Deploy:** Windows 11 local sin containerización — mismo approach que tu otro proyecto. Uvicorn corriendo directo, sin Docker.
- **Reset de DB:** acción destructiva (dropea y recrea tablas, reseedea al superadmin inicial). En `/admin/settings` conviene pedir una confirmación explícita (ej. escribir el nombre de la app) antes de ejecutar, y registrar la acción en `activity_log` con `user_id=null` o el superadmin que la ejecutó. "Inicializar" (crear tablas si no existen) es no destructivo y puede vivir en la misma pantalla sin esa fricción.

## 10. Próximos Pasos

1. Confirmar este documento (ajustar lo que no cierre).
2. Pasar a Claude Code para scaffolding del proyecto (estructura de carpetas + modelos + migraciones iniciales).
3. Implementar auth + invitaciones primero (es la base de todo lo demás).
4. Sumar integración TMDB y alta de sugerencias.
5. Watchlist y comentarios al final, son los más simples una vez que el resto está andando.
