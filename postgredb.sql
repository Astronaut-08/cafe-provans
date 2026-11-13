CREATE "EXTENSION" IF NOT EXISTS vector;

CREATE TYPE "user_role" AS ENUM (
  'admin',
  'manager',
  'operator'
);

CREATE TYPE "fulfillment_type" AS ENUM (
  'delivery',
  'pickup'
);

CREATE TYPE "order_status" AS ENUM (
  'new',
  'confirmed',
  'preparing',
  'ready',
  'out_for_delivery',
  'completed',
  'cancelled'
);

CREATE TYPE "payment_status" AS ENUM (
  'unpaid',
  'pending',
  'paid',
  'failed',
  'refunded'
);

CREATE TYPE "order_source" AS ENUM (
  'ai_chat',
  'operator',
  'website'
);

CREATE TYPE "promotion_status" AS ENUM (
  'draft',
  'active',
  'paused',
  'archived'
);

CREATE TYPE "dialog_status" AS ENUM (
  'active',
  'waiting_human',
  'closed'
);

CREATE TYPE "message_role" AS ENUM (
  'user',
  'assistant',
  'system',
  'tool',
  'operator'
);

CREATE TABLE "locations" (
  "id" serial PRIMARY KEY,
  "name" varchar NOT NULL,
  "address" varchar,
  "phone" varchar,
  "instagram" varchar,
  "opening_time" time,
  "closing_time" time,
  "timezone" varchar NOT NULL DEFAULT 'Europe/Kyiv',
  "is_active" boolean NOT NULL DEFAULT true
);

CREATE TABLE "users" (
  "id" serial PRIMARY KEY,
  "phone" varchar UNIQUE NOT NULL,
  "full_name" varchar,
  "role" user_role NOT NULL,
  "location_id" integer,
  "created_at" timestamptz NOT NULL DEFAULT (now())
);

CREATE TABLE "categories" (
  "id" serial PRIMARY KEY,
  "name" varchar NOT NULL,
  "sort_order" integer NOT NULL DEFAULT 0
);

CREATE TABLE "dishes" (
  "id" serial PRIMARY KEY,
  "category_id" integer NOT NULL,
  "name" varchar NOT NULL,
  "description" text,
  "price" decimal(10,2) NOT NULL,
  "weight" integer,
  "diameter" integer,
  "image_url" varchar,
  "badge" varchar,
  "is_available" boolean NOT NULL DEFAULT true,
  "show_on_home" boolean NOT NULL DEFAULT false,
  "embedding" vector(1536),
  "created_at" timestamptz NOT NULL DEFAULT (now()),
  "embedding_model" varchar(100),
  "embedding_updated_at" timestamptz NOT NULL DEFAULT (now()),
  "embedding_content_hash" varchar(64)
);

CREATE TABLE "dish_locations" (
  "dish_id" integer NOT NULL,
  "location_id" integer NOT NULL,
  "is_available" boolean NOT NULL DEFAULT true,
  "price_override" decimal(10,2),
  PRIMARY KEY ("dish_id", "location_id")
);

CREATE TABLE "allergens" (
  "id" serial PRIMARY KEY,
  "code" varchar UNIQUE NOT NULL,
  "name" varchar NOT NULL
);

CREATE TABLE "dish_allergens" (
  "dish_id" integer NOT NULL,
  "allergen_id" integer NOT NULL,
  PRIMARY KEY ("dish_id", "allergen_id")
);

CREATE TABLE "promotions" (
  "id" serial PRIMARY KEY,
  "title" varchar NOT NULL,
  "description" text,
  "status" promotion_status NOT NULL DEFAULT 'draft',
  "custom_price" decimal(10,2),
  "auto_calculate_price" boolean NOT NULL DEFAULT false,
  "start_time" time,
  "end_time" time,
  "start_date" date,
  "end_date" date,
  "show_on_home" boolean NOT NULL DEFAULT false,
  "pause_if_unavailable" boolean NOT NULL DEFAULT true,
  "embedding" vector(1536),
  "created_at" timestamptz NOT NULL DEFAULT (now())
  "embedding_model" varchar(100),
  "embedding_updated_at" timestamptz NOT NULL DEFAULT (now()),
  "embedding_content_hash" varchar(64)
);

CREATE TABLE "promotion_items" (
  "id" serial PRIMARY KEY,
  "promotion_id" integer NOT NULL,
  "dish_id" integer NOT NULL,
  "quantity" integer NOT NULL DEFAULT 1
);

CREATE TABLE "promotion_locations" (
  "promotion_id" integer NOT NULL,
  "location_id" integer NOT NULL,
  PRIMARY KEY ("promotion_id", "location_id")
);

CREATE TABLE "customers" (
  "id" serial PRIMARY KEY,
  "phone" varchar UNIQUE NOT NULL,
  "full_name" varchar,
  "created_at" timestamptz NOT NULL DEFAULT (now())
);

CREATE TABLE "customer_addresses" (
  "id" serial PRIMARY KEY,
  "customer_id" integer NOT NULL,
  "address" text NOT NULL,
  "comment" varchar,
  "is_default" boolean NOT NULL DEFAULT false
);

CREATE TABLE "orders" (
  "id" serial PRIMARY KEY,
  "order_number" varchar UNIQUE NOT NULL,
  "location_id" integer NOT NULL,
  "customer_id" integer NOT NULL,
  "dialog_id" integer,
  "source" order_source NOT NULL DEFAULT 'ai_chat',
  "fulfillment_type" fulfillment_type NOT NULL,
  "delivery_address" text,
  "status" order_status NOT NULL DEFAULT 'new',
  "payment_status" payment_status NOT NULL DEFAULT 'unpaid',
  "subtotal_price" decimal(10,2) NOT NULL,
  "delivery_price" decimal(10,2) NOT NULL DEFAULT 0,
  "total_price" decimal(10,2) NOT NULL,
  "operator_notes" text,
  "created_at" timestamptz NOT NULL DEFAULT (now()),
  "updated_at" timestamptz NOT NULL DEFAULT (now())
);

CREATE TABLE "order_items" (
  "id" serial PRIMARY KEY,
  "order_id" integer NOT NULL,
  "dish_id" integer,
  "promotion_id" integer,
  "name" varchar NOT NULL,
  "unit_price" decimal(10,2) NOT NULL,
  "quantity" integer NOT NULL DEFAULT 1,
  "line_total" decimal(10,2) NOT NULL,
  "note" varchar
);

CREATE TABLE "order_status_history" (
  "id" serial PRIMARY KEY,
  "order_id" integer NOT NULL,
  "status" order_status NOT NULL,
  "changed_by" integer,
  "comment" varchar,
  "created_at" timestamptz NOT NULL DEFAULT (now())
);

CREATE TABLE "payments" (
  "id" serial PRIMARY KEY,
  "order_id" integer NOT NULL,
  "provider" varchar NOT NULL,
  "external_id" varchar,
  "amount" decimal(10,2) NOT NULL,
  "status" payment_status NOT NULL DEFAULT 'pending',
  "raw_payload" jsonb,
  "created_at" timestamptz NOT NULL DEFAULT (now())
);

CREATE TABLE "ai_settings" (
  "id" serial PRIMARY KEY,
  "location_id" integer UNIQUE NOT NULL,
  "tone_of_voice" text,
  "check_allergies" boolean NOT NULL DEFAULT true,
  "forward_allergies_to_human" boolean NOT NULL DEFAULT true,
  "require_guest_confirmation" boolean NOT NULL DEFAULT true,
  "escalation_channel" varchar
);

CREATE TABLE "ai_escalation_triggers" (
  "id" serial PRIMARY KEY,
  "ai_settings_id" integer NOT NULL,
  "trigger_text" varchar NOT NULL
);

CREATE TABLE "ai_dialogs" (
  "id" serial PRIMARY KEY,
  "customer_id" integer NOT NULL,
  "location_id" integer NOT NULL,
  "channel" varchar NOT NULL,
  "external_chat_id" varchar,
  "status" dialog_status NOT NULL DEFAULT 'active',
  "dialog_state" jsonb,
  "verified_by" integer,
  "verified_at" timestamptz,
  "created_at" timestamptz NOT NULL DEFAULT (now()),
  "updated_at" timestamptz NOT NULL DEFAULT (now())
);

CREATE TABLE "ai_messages" (
  "id" bigserial PRIMARY KEY,
  "dialog_id" integer NOT NULL,
  "role" message_role NOT NULL,
  "content" text NOT NULL,
  "meta" jsonb,
  "created_at" timestamptz NOT NULL DEFAULT (now())
);

CREATE INDEX ON "dishes" ("category_id");

CREATE INDEX ON "dish_locations" ("location_id");

CREATE INDEX ON "dish_allergens" ("allergen_id");

CREATE UNIQUE INDEX ON "promotion_items" ("promotion_id", "dish_id");

CREATE INDEX ON "promotion_items" ("dish_id");

CREATE INDEX ON "promotion_locations" ("location_id");

CREATE INDEX ON "customer_addresses" ("customer_id");

CREATE INDEX "idx_orders_location_created" ON "orders" ("location_id", "created_at");

CREATE INDEX "idx_orders_customer_created" ON "orders" ("customer_id", "created_at");

CREATE INDEX ON "order_items" ("order_id");

CREATE INDEX ON "order_items" ("dish_id");

CREATE INDEX ON "order_items" ("promotion_id");

CREATE INDEX ON "order_status_history" ("order_id", "created_at");

CREATE INDEX ON "payments" ("order_id");

CREATE UNIQUE INDEX ON "payments" ("provider", "external_id");

CREATE UNIQUE INDEX ON "ai_escalation_triggers" ("ai_settings_id", "trigger_text");

CREATE INDEX ON "ai_dialogs" ("customer_id", "created_at");

CREATE INDEX ON "ai_dialogs" ("channel", "external_chat_id");

CREATE INDEX ON "ai_dialogs" ("location_id", "status");

CREATE INDEX ON "ai_messages" ("dialog_id", "created_at");

CREATE INDEX idx_dishes_embedding
ON "dishes"
USING "hnsw" ("embedding", "vector_cosine_ops");

CREATE INDEX idx_promotions_embedding
ON "promotions"
USING "hnsw" ("embedding", "vector_cosine_ops");

COMMENT ON TABLE "users" IS 'Тільки персонал (адмін, менеджер, оператор). Гості в customers';

COMMENT ON COLUMN "dish_locations"."price_override" IS 'NULL = беремо dishes.price';

COMMENT ON COLUMN "allergens"."code" IS 'gluten, lactose, nuts ...';

COMMENT ON TABLE "promotions" IS 'CHECK (припущення): рівно одне з двох, або custom_price заповнене, або auto_calculate_price = true';

COMMENT ON COLUMN "customer_addresses"."comment" IS 'під''їзд, поверх, домофон';

COMMENT ON TABLE "orders" IS 'Суми зафіксовані навмисно (денормалізація для фінансів). Правила для БД:
CHECK (total_price = subtotal_price + delivery_price)
subtotal_price = сума order_items.line_total (тригер або перевірка в застосунку)
status = останній рядок order_status_history (оновлювати в одній транзакції)
payment_status = підсумок за payments (так само в одній транзакції)
customer_id і location_id мають збігатися з ai_dialogs, якщо заповнений dialog_id
';

COMMENT ON COLUMN "orders"."dialog_id" IS 'NULL, якщо замовлення не з AI-чату';

COMMENT ON COLUMN "orders"."delivery_address" IS 'копія адреси на момент замовлення';

COMMENT ON TABLE "order_items" IS 'CHECK: рівно одне з dish_id / promotion_id заповнене
CHECK (quantity > 0)
Страви не видаляємо (ON DELETE RESTRICT), а знімаємо з продажу через is_available
line_total у БД: GENERATED ALWAYS AS (unit_price * quantity) STORED
';

COMMENT ON COLUMN "order_items"."dish_id" IS 'NULL, якщо позиція з акції';

COMMENT ON COLUMN "order_items"."name" IS 'назва на момент замовлення';

COMMENT ON COLUMN "order_items"."unit_price" IS 'ціна на момент замовлення';

COMMENT ON COLUMN "order_items"."line_total" IS 'generated: unit_price * quantity';

COMMENT ON COLUMN "order_status_history"."changed_by" IS 'NULL = система або AI';

COMMENT ON COLUMN "payments"."external_id" IS 'id транзакції у провайдера';

COMMENT ON COLUMN "payments"."raw_payload" IS 'вебхук провайдера';

COMMENT ON COLUMN "ai_escalation_triggers"."trigger_text" IS 'фраза або ситуація, коли діалог передається людині';

COMMENT ON TABLE "ai_dialogs" IS 'CHECK: verified_by і verified_at або обидва NULL, або обидва заповнені';

COMMENT ON COLUMN "ai_dialogs"."channel" IS 'telegram, instagram, web ...';

COMMENT ON COLUMN "ai_dialogs"."dialog_state" IS 'тільки компактний стан: кошик, поточний крок';

COMMENT ON COLUMN "ai_dialogs"."verified_by" IS 'NULL = не перевірено людиною';

COMMENT ON TABLE "ai_messages" IS 'Append-only. Історія повідомлень для дебагу та аудиту ескалацій';

COMMENT ON COLUMN "ai_messages"."meta" IS 'виклики інструментів, токени, модель';

ALTER TABLE "users" ADD FOREIGN KEY ("location_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "dishes" ADD FOREIGN KEY ("category_id") REFERENCES "categories" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "dish_locations" ADD FOREIGN KEY ("dish_id") REFERENCES "dishes" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "dish_locations" ADD FOREIGN KEY ("location_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "dish_allergens" ADD FOREIGN KEY ("dish_id") REFERENCES "dishes" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "dish_allergens" ADD FOREIGN KEY ("allergen_id") REFERENCES "allergens" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "promotion_items" ADD FOREIGN KEY ("promotion_id") REFERENCES "promotions" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "promotion_items" ADD FOREIGN KEY ("dish_id") REFERENCES "dishes" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "promotion_locations" ADD FOREIGN KEY ("promotion_id") REFERENCES "promotions" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "promotion_locations" ADD FOREIGN KEY ("location_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "customer_addresses" ADD FOREIGN KEY ("customer_id") REFERENCES "customers" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "orders" ADD FOREIGN KEY ("location_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "orders" ADD FOREIGN KEY ("customer_id") REFERENCES "customers" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "orders" ADD FOREIGN KEY ("dialog_id") REFERENCES "ai_dialogs" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "order_items" ADD FOREIGN KEY ("order_id") REFERENCES "orders" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "order_items" ADD FOREIGN KEY ("dish_id") REFERENCES "dishes" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "order_items" ADD FOREIGN KEY ("promotion_id") REFERENCES "promotions" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "order_status_history" ADD FOREIGN KEY ("order_id") REFERENCES "orders" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "order_status_history" ADD FOREIGN KEY ("changed_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "payments" ADD FOREIGN KEY ("order_id") REFERENCES "orders" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ai_settings" ADD FOREIGN KEY ("location_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ai_escalation_triggers" ADD FOREIGN KEY ("ai_settings_id") REFERENCES "ai_settings" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ai_dialogs" ADD FOREIGN KEY ("customer_id") REFERENCES "customers" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ai_dialogs" ADD FOREIGN KEY ("location_id") REFERENCES "locations" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ai_dialogs" ADD FOREIGN KEY ("verified_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "ai_messages" ADD FOREIGN KEY ("dialog_id") REFERENCES "ai_dialogs" ("id") DEFERRABLE INITIALLY IMMEDIATE;
