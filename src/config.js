import { existsSync, readFileSync, writeFileSync } from "fs";
import { parse } from "dotenv";

import {
  CONFIG_FILE,
  ENV_FILE,
  MEMORY_DB_FILE,
  SESSION_FILE,
  TAXSENTRY_HOME,
  ensureDirectories,
} from "./utils/paths.js";

const DEFAULT_CONFIG = {
  version: "1.1.2",
  configured: false,
  agent: {
    name: "TaxSentry",
    persona: "warm, precise, and practical",
    language: "vi",
    memoryEnabled: true,
    welcomeMessage: "Chào Sếp, em là TaxSentry — trợ lý agent local-first.",
  },
  provider: {
    kind: "lmstudio",
    baseUrl: "http://localhost:1234/v1",
    model: "google/gemma-4-e4b",
    apiKey: "",
    authMode: "lmstudio",
  },
  memory: {
    maxFacts: 50,
    maxTurns: 12,
    sessionTitle: "TaxSentry session",
  },
  jobs: {
    trackingEnabled: true,
    retryLimit: 2,
    defaultState: "pending",
    needsHumanReviewOnMissingData: true,
    autoSendEmail: true,
    autoSendTelegram: true,
  },
  integrations: {
    telegram: {
      enabled: false,
      botToken: "",
      adminChatId: "",
    },
  },
  ui: {
    theme: "midnight",
    showBanner: true,
  },
  extraEnv: {},
};

const SECRET_PATHS = [
  ["provider", "apiKey"],
  ["integrations", "telegram", "botToken"],
];

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function deepMerge(base, override) {
  if (override === null || override === undefined) return deepClone(base);
  if (Array.isArray(base) || Array.isArray(override)) return deepClone(override);
  if (typeof base !== "object" || typeof override !== "object") return deepClone(override);
  const out = deepClone(base);
  for (const [key, value] of Object.entries(override)) {
    if (
      value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      base[key] &&
      typeof base[key] === "object" &&
      !Array.isArray(base[key])
    ) {
      out[key] = deepMerge(base[key], value);
    } else {
      out[key] = deepClone(value);
    }
  }
  return out;
}

function getByPath(obj, path) {
  return path.reduce(
    (cursor, part) => (cursor && Object.prototype.hasOwnProperty.call(cursor, part) ? cursor[part] : undefined),
    obj,
  );
}

function setByPath(obj, path, value) {
  let cursor = obj;
  for (let i = 0; i < path.length - 1; i += 1) {
    const part = path[i];
    if (!cursor[part] || typeof cursor[part] !== "object") cursor[part] = {};
    cursor = cursor[part];
  }
  cursor[path[path.length - 1]] = value;
}

function sanitizeForDisk(config) {
  const out = deepClone(config);
  for (const path of SECRET_PATHS) {
    setByPath(out, path, "");
  }
  return out;
}

function envValue(config, path, fallback = "") {
  const value = getByPath(config, path.split("."));
  return value === undefined || value === null ? fallback : value;
}

export function getEmptyConfig() {
  const out = deepClone(DEFAULT_CONFIG);
  out.paths = {
    home: TAXSENTRY_HOME,
    configFile: CONFIG_FILE,
    memoryDb: MEMORY_DB_FILE,
    sessionFile: SESSION_FILE,
  };
  return out;
}

export function getValue(config, section, key) {
  if (!config || typeof config !== "object") return undefined;
  return config?.[section]?.[key];
}

export function setValue(config, section, key, value) {
  if (!config[section] || typeof config[section] !== "object") config[section] = {};
  config[section][key] = value;
  return config;
}

export function loadConfig() {
  ensureDirectories();
  let config = getEmptyConfig();

  if (existsSync(CONFIG_FILE)) {
    try {
      const parsed = JSON.parse(readFileSync(CONFIG_FILE, "utf8"));
      if (parsed && typeof parsed === "object") config = deepMerge(config, parsed);
    } catch {
      // Ignore unreadable config files and keep defaults.
    }
  }

  const envFileValues = existsSync(ENV_FILE) ? parse(readFileSync(ENV_FILE, "utf8")) : {};
  const envPairs = {
    TAXSENTRY_AGENT_NAME: process.env.TAXSENTRY_AGENT_NAME ?? envFileValues.TAXSENTRY_AGENT_NAME,
    TAXSENTRY_AGENT_PERSONA: process.env.TAXSENTRY_AGENT_PERSONA ?? envFileValues.TAXSENTRY_AGENT_PERSONA,
    TAXSENTRY_LANGUAGE: process.env.TAXSENTRY_LANGUAGE ?? envFileValues.TAXSENTRY_LANGUAGE,
    TAXSENTRY_MEMORY_ENABLED: process.env.TAXSENTRY_MEMORY_ENABLED ?? envFileValues.TAXSENTRY_MEMORY_ENABLED,
    TAXSENTRY_PROVIDER_KIND: process.env.TAXSENTRY_PROVIDER_KIND ?? envFileValues.TAXSENTRY_PROVIDER_KIND,
    TAXSENTRY_PROVIDER_URL: process.env.TAXSENTRY_PROVIDER_URL ?? envFileValues.TAXSENTRY_PROVIDER_URL,
    TAXSENTRY_PROVIDER_MODEL: process.env.TAXSENTRY_PROVIDER_MODEL ?? envFileValues.TAXSENTRY_PROVIDER_MODEL,
    TAXSENTRY_PROVIDER_API_KEY: process.env.TAXSENTRY_PROVIDER_API_KEY ?? envFileValues.TAXSENTRY_PROVIDER_API_KEY,
    TAXSENTRY_AI_AUTH_MODE: process.env.TAXSENTRY_AI_AUTH_MODE ?? envFileValues.TAXSENTRY_AI_AUTH_MODE,
    TAXSENTRY_MEMORY_MAX_FACTS: process.env.TAXSENTRY_MEMORY_MAX_FACTS ?? envFileValues.TAXSENTRY_MEMORY_MAX_FACTS,
    TAXSENTRY_MEMORY_MAX_TURNS: process.env.TAXSENTRY_MEMORY_MAX_TURNS ?? envFileValues.TAXSENTRY_MEMORY_MAX_TURNS,
    TAXSENTRY_SESSION_TITLE: process.env.TAXSENTRY_SESSION_TITLE ?? envFileValues.TAXSENTRY_SESSION_TITLE,
    TAXSENTRY_JOB_TRACKING: process.env.TAXSENTRY_JOB_TRACKING ?? envFileValues.TAXSENTRY_JOB_TRACKING,
    TAXSENTRY_JOB_RETRY_LIMIT: process.env.TAXSENTRY_JOB_RETRY_LIMIT ?? envFileValues.TAXSENTRY_JOB_RETRY_LIMIT,
    TAXSENTRY_JOB_DEFAULT_STATE: process.env.TAXSENTRY_JOB_DEFAULT_STATE ?? envFileValues.TAXSENTRY_JOB_DEFAULT_STATE,
    TAXSENTRY_JOB_NEEDS_HUMAN_REVIEW_ON_MISSING_DATA:
      process.env.TAXSENTRY_JOB_NEEDS_HUMAN_REVIEW_ON_MISSING_DATA ??
      envFileValues.TAXSENTRY_JOB_NEEDS_HUMAN_REVIEW_ON_MISSING_DATA,
    AUTO_SEND_EMAIL: process.env.AUTO_SEND_EMAIL ?? envFileValues.AUTO_SEND_EMAIL,
    AUTO_SEND_TELEGRAM: process.env.AUTO_SEND_TELEGRAM ?? envFileValues.AUTO_SEND_TELEGRAM,
    TELEGRAM_ENABLED: process.env.TELEGRAM_ENABLED ?? envFileValues.TELEGRAM_ENABLED,
    TELEGRAM_BOT_TOKEN: process.env.TELEGRAM_BOT_TOKEN ?? envFileValues.TELEGRAM_BOT_TOKEN,
    ADMIN_CHAT_ID: process.env.ADMIN_CHAT_ID ?? envFileValues.ADMIN_CHAT_ID,
    TAXSENTRY_THEME: process.env.TAXSENTRY_THEME ?? envFileValues.TAXSENTRY_THEME,
    TAXSENTRY_SHOW_BANNER: process.env.TAXSENTRY_SHOW_BANNER ?? envFileValues.TAXSENTRY_SHOW_BANNER,
  };

  const fieldMap = {
    TAXSENTRY_AGENT_NAME: ["agent", "name"],
    TAXSENTRY_AGENT_PERSONA: ["agent", "persona"],
    TAXSENTRY_LANGUAGE: ["agent", "language"],
    TAXSENTRY_MEMORY_ENABLED: ["agent", "memoryEnabled"],
    TAXSENTRY_PROVIDER_KIND: ["provider", "kind"],
    TAXSENTRY_PROVIDER_URL: ["provider", "baseUrl"],
    TAXSENTRY_PROVIDER_MODEL: ["provider", "model"],
    TAXSENTRY_PROVIDER_API_KEY: ["provider", "apiKey"],
    TAXSENTRY_AI_AUTH_MODE: ["provider", "authMode"],
    TAXSENTRY_MEMORY_MAX_FACTS: ["memory", "maxFacts"],
    TAXSENTRY_MEMORY_MAX_TURNS: ["memory", "maxTurns"],
    TAXSENTRY_SESSION_TITLE: ["memory", "sessionTitle"],
    TAXSENTRY_JOB_TRACKING: ["jobs", "trackingEnabled"],
    TAXSENTRY_JOB_RETRY_LIMIT: ["jobs", "retryLimit"],
    TAXSENTRY_JOB_DEFAULT_STATE: ["jobs", "defaultState"],
    TAXSENTRY_JOB_NEEDS_HUMAN_REVIEW_ON_MISSING_DATA: ["jobs", "needsHumanReviewOnMissingData"],
    AUTO_SEND_EMAIL: ["jobs", "autoSendEmail"],
    AUTO_SEND_TELEGRAM: ["jobs", "autoSendTelegram"],
    TELEGRAM_ENABLED: ["integrations", "telegram", "enabled"],
    TELEGRAM_BOT_TOKEN: ["integrations", "telegram", "botToken"],
    ADMIN_CHAT_ID: ["integrations", "telegram", "adminChatId"],
    TAXSENTRY_THEME: ["ui", "theme"],
    TAXSENTRY_SHOW_BANNER: ["ui", "showBanner"],
  };

  for (const [envName, raw] of Object.entries(envPairs)) {
    if (raw === undefined || raw === "") continue;
    const path = fieldMap[envName];
    if (!path) continue;
    if (
      envName === "TAXSENTRY_MEMORY_ENABLED" ||
      envName === "TELEGRAM_ENABLED" ||
      envName === "TAXSENTRY_SHOW_BANNER" ||
      envName === "TAXSENTRY_JOB_TRACKING" ||
      envName === "TAXSENTRY_JOB_NEEDS_HUMAN_REVIEW_ON_MISSING_DATA" ||
      envName === "AUTO_SEND_EMAIL" ||
      envName === "AUTO_SEND_TELEGRAM"
    ) {
      setByPath(config, path, /^(1|true|yes|on)$/i.test(raw));
    } else if (
      envName === "TAXSENTRY_MEMORY_MAX_FACTS" ||
      envName === "TAXSENTRY_MEMORY_MAX_TURNS" ||
      envName === "TAXSENTRY_JOB_RETRY_LIMIT"
    ) {
      const parsed = Number.parseInt(raw, 10);
      if (!Number.isNaN(parsed)) setByPath(config, path, parsed);
    } else {
      setByPath(config, path, raw);
    }
  }

  config.paths = {
    home: TAXSENTRY_HOME,
    configFile: CONFIG_FILE,
    memoryDb: MEMORY_DB_FILE,
    sessionFile: SESSION_FILE,
  };
  return config;
}

export function saveConfig(config) {
  ensureDirectories();
  const payload = sanitizeForDisk(config);
  writeFileSync(CONFIG_FILE, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

export function buildEnvLines(config) {
  const provider = config.provider || {};
  const agent = config.agent || {};
  const memory = config.memory || {};
  const telegram = config.integrations?.telegram || {};
  const lines = [
    `TAXSENTRY_HOME=${JSON.stringify(TAXSENTRY_HOME)}`,
    `TAXSENTRY_CONFIG_FILE=${JSON.stringify(CONFIG_FILE)}`,
    `TAXSENTRY_MEMORY_DB=${JSON.stringify(MEMORY_DB_FILE)}`,
    `TAXSENTRY_SESSION_FILE=${JSON.stringify(SESSION_FILE)}`,
    `TAXSENTRY_AGENT_NAME=${JSON.stringify(envValue(config, "agent.name", agent.name || "TaxSentry"))}`,
    `TAXSENTRY_AGENT_PERSONA=${JSON.stringify(envValue(config, "agent.persona", agent.persona || "practical"))}`,
    `TAXSENTRY_LANGUAGE=${JSON.stringify(envValue(config, "agent.language", agent.language || "vi"))}`,
    `TAXSENTRY_MEMORY_ENABLED=${JSON.stringify(String(Boolean(envValue(config, "agent.memoryEnabled", true))).toLowerCase())}`,
    `TAXSENTRY_PROVIDER_KIND=${JSON.stringify(envValue(config, "provider.kind", provider.kind || "lmstudio"))}`,
    `TAXSENTRY_PROVIDER_URL=${JSON.stringify(envValue(config, "provider.baseUrl", provider.baseUrl || "http://localhost:1234/v1"))}`,
    `TAXSENTRY_PROVIDER_MODEL=${JSON.stringify(envValue(config, "provider.model", provider.model || "google/gemma-4-e4b"))}`,
    `TAXSENTRY_AI_AUTH_MODE=${JSON.stringify(envValue(config, "provider.authMode", provider.authMode || "lmstudio"))}`,
    `TAXSENTRY_MEMORY_MAX_FACTS=${JSON.stringify(String(Number(envValue(config, "memory.maxFacts", memory.maxFacts ?? 50))))}`,
    `TAXSENTRY_MEMORY_MAX_TURNS=${JSON.stringify(String(Number(envValue(config, "memory.maxTurns", memory.maxTurns ?? 12))))}`,
    `TAXSENTRY_SESSION_TITLE=${JSON.stringify(envValue(config, "memory.sessionTitle", memory.sessionTitle || "TaxSentry session"))}`,
    `TAXSENTRY_JOB_TRACKING=${JSON.stringify(String(Boolean(envValue(config, "jobs.trackingEnabled", true))).toLowerCase())}`,
    `TAXSENTRY_JOB_RETRY_LIMIT=${JSON.stringify(String(Number(envValue(config, "jobs.retryLimit", 2))))}`,
    `TAXSENTRY_JOB_DEFAULT_STATE=${JSON.stringify(envValue(config, "jobs.defaultState", "pending"))}`,
    `TAXSENTRY_JOB_NEEDS_HUMAN_REVIEW_ON_MISSING_DATA=${JSON.stringify(String(Boolean(envValue(config, "jobs.needsHumanReviewOnMissingData", true))).toLowerCase())}`,
    `AUTO_SEND_EMAIL=${JSON.stringify(String(Boolean(envValue(config, "jobs.autoSendEmail", true))).toLowerCase())}`,
    `AUTO_SEND_TELEGRAM=${JSON.stringify(String(Boolean(envValue(config, "jobs.autoSendTelegram", true))).toLowerCase())}`,
    `TELEGRAM_ENABLED=${JSON.stringify(String(Boolean(envValue(config, "integrations.telegram.enabled", telegram.enabled || false))).toLowerCase())}`,
    `TELEGRAM_BOT_TOKEN=${JSON.stringify(envValue(config, "integrations.telegram.botToken", telegram.botToken || ""))}`,
    `ADMIN_CHAT_ID=${JSON.stringify(envValue(config, "integrations.telegram.adminChatId", telegram.adminChatId || ""))}`,
  ];

  if (provider.apiKey) {
    lines.push(`TAXSENTRY_PROVIDER_API_KEY=${JSON.stringify(provider.apiKey)}`);
  }

  for (const [key, value] of Object.entries(config.extraEnv || {})) {
    lines.push(`${key}=${JSON.stringify(String(value))}`);
  }

  return lines;
}

export function writeEnvFile(config) {
  ensureDirectories();
  writeFileSync(ENV_FILE, `${buildEnvLines(config).join("\n")}\n`, "utf8");
}

export function isConfigured() {
  return existsSync(CONFIG_FILE) && existsSync(ENV_FILE);
}

export function describeConfig(config) {
  return [
    `Agent: ${config.agent.name} (${config.agent.persona}, ${config.agent.language})`,
    `Provider: ${config.provider.kind} / ${config.provider.model}`,
    `Endpoint: ${config.provider.baseUrl}`,
    `Memory: ${config.agent.memoryEnabled ? "on" : "off"} · facts=${config.memory.maxFacts} · turns=${config.memory.maxTurns}`,
    `Jobs: ${config.jobs.trackingEnabled ? "tracking on" : "tracking off"} · retry=${config.jobs.retryLimit} · default=${config.jobs.defaultState} · review=${config.jobs.needsHumanReviewOnMissingData ? "on" : "off"} · email=${config.jobs.autoSendEmail ? "on" : "off"} · telegram=${config.jobs.autoSendTelegram ? "on" : "off"}`,
    `Telegram: ${config.integrations.telegram.enabled ? "enabled" : "disabled"}`,
    `Config file: ${CONFIG_FILE}`,
    `Memory DB: ${MEMORY_DB_FILE}`,
  ].join("\n");
}
