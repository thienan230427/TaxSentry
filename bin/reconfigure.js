/**
 * TaxSentry Reconfigure Script
 * Đọc config.json hiện tại + regenerate .env + verify all fixes.
 * Không cần chạy wizard interactive~!
 */

import { readFileSync, writeFileSync, existsSync } from 'fs';
import { join } from 'path';
import {
  loadConfig,
  saveConfig,
  writeEnvFile,
  isConfigured,
} from '../src/config.js';

import { ENV_FILE, CORE_DIR, CONFIG_FILE } from '../src/utils/paths.js';

const logo = `
  _____             ____                _
 |_   _|__ _ __  __/ ___|   ___  _ __  | |_  _ __  _   _
   | | / __\` |\\ \\/ /\\___ \\  / _ \\| '_ \\ | __|| '__|| | | |
   | || (_| | >  <  ___) ||  __/| | | || |_ | |   | |_| |
   |_| \\__,_|/_/\\_\\|____/  \\___||_| |_| \\__||_|    \\__, |
                                                   |___/
`;

console.log(logo);
console.log('╭─────────────────────────────────────────────╮');
console.log('│ 🔄 TaxSentry Reconfigure Tool               │');
console.log('│ Đọc config cũ + Regenerate .env + Verify    │');
console.log('╰─────────────────────────────────────────────╯');
console.log();

// === 1. Load existing config ===
if (!existsSync(CONFIG_FILE)) {
  console.log('❌ Không tìm thấy config.json!');
  console.log(`   Chạy "taxsentry setup" trước khi dùng tool này.`);
  process.exit(1);
}

const config = loadConfig();
console.log('✅ Đã load config.json');
console.log(`   Version: ${config.version}`);
console.log();

// === 2. Clean "undefined" keys (safety net) ===
let cleaned = false;
for (const gid of Object.keys(config.values || {})) {
  const gval = config.values[gid];
  if (typeof gval === 'object' && gval && 'undefined' in gval) {
    const undef = { ...gval['undefined'] };
    delete gval['undefined'];
    for (const [k, v] of Object.entries(undef)) {
      if (!gval[k] || gval[k] === '') gval[k] = v;
    }
    cleaned = true;
  }
}
if (cleaned) {
  console.log('🧹 Đã dọn "undefined" keys trong config.json');
  saveConfig(config);
}

// === 3. Add missing fields to envMapping (safety net) ===
const requiredMappings = {
  'director.directorEmail': 'DIRECTOR_EMAIL',
  'email.accountantEmail': 'ACCOUNTANT_EMAIL',
};
let mappingAdded = false;
for (const [path, envVar] of Object.entries(requiredMappings)) {
  if (!config.envMapping[path]) {
    config.envMapping[path] = envVar;
    mappingAdded = true;
  }
}
if (mappingAdded) {
  console.log('🔧 Đã thêm missing envMappings');
  saveConfig(config);
}

// === 4. Regenerate .env ===
writeEnvFile(config);
console.log('✅ Đã regenerate .env từ config.json');
console.log(`   Path: ${ENV_FILE}`);
console.log();

// === 5. Verify .env content (không show secrets) ===
if (existsSync(ENV_FILE)) {
  const envContent = readFileSync(ENV_FILE, 'utf-8');
  const envLines = envContent.split('\n').filter(l => l && !l.startsWith('#'));
  
  console.log('📋 .env nội dung (ẩn secrets):');
  for (const line of envLines) {
    const key = line.split('=')[0];
    if (['EMAIL_PASS', 'DB_PASS', 'LM_STUDIO_API_KEY'].includes(key)) continue;
    if (line.includes('[LƯU TRONG BITWARDEN]')) {
      console.log(`   ${key}=[LƯU TRONG BITWARDEN]`);
      continue;
    }
    console.log(`   ${line}`);
  }
  console.log();
}

// === 6. Verify .env từ config.js perspective ===
console.log('🔍 Verification:');
console.log(`   Config file: ${CONFIG_FILE}`);
console.log(`   Env file:    ${ENV_FILE}`);
console.log(`   Core dir:    ${CORE_DIR}`);
console.log();

// Check isConfigured
const ok = isConfigured();
console.log(`   isConfigured(): ${ok ? '✅ YES' : '⚠️ NO — cần chạy "taxsentry setup" đầy đủ'}`);

// === 7. Clear processed_ids (để email re-scan) ===
const processedFile = join(CORE_DIR, '.processed_ids.json');
if (existsSync(processedFile)) {
  writeFileSync(processedFile, JSON.stringify({ ids: [] }, null, 2), 'utf-8');
  console.log('   🧹 Cleared processed_ids.json (email sẽ re-scan)');
}

// === 8. Sync config.js schema fields into installed config.json ===
// đảm bảo accountantEmail + directorEmail có value mặc định nếu chưa có
const groups = ['director', 'telegram', 'mysql', 'email'];
for (const gid of groups) {
  if (!config.values[gid]) config.values[gid] = {};
}
saveConfig(config);

console.log();
console.log('═══════════════════════════════════════════════');
console.log('✅ Hoàn tất reconfigure!');
console.log();
console.log('   🚀 Bước tiếp: chạy "taxsentry up" để khởi động TUI + Bot');
console.log('   📝 Hoặc "taxsentry config" để xem/thay đổi cấu hình');
console.log('═══════════════════════════════════════════════');
