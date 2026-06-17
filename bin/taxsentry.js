#!/usr/bin/env node

/**
 * 🛡️ TaxSentry CLI - Entry Point
 * Phase 1: Bootstrap & Basic CLI Dispatcher
 */

import { execSync } from 'child_process';
import { existsSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

// ASCII Art Banner
const banner = `
  ████████╗██╗  ██╗██████╗  ██████╗ ██████╗ 
  ╚══██╔══╝██║  ██║██╔══██╗██╔═══██╗██╔══██╗
     ██║   ███████║██████╔╝██║   ██║██████╔╝
     ██║   ██╔══██║██╔══██╗██║   ██║██╔══██╗
     ██║   ██║  ██║██║  ██║╚██████╔╝██║  ██║
     ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝
         🛡️ On-premise AI Tax Audit Agent
`;

console.log(banner);

// Basic command handler (Placeholder for Phase 2+)
const command = process.argv[2] || 'start';

if (command === 'start' || command === 'help' || !command) {
  console.log("🚀 [Phase 1 Bootstrap] TaxSentry CLI đã được khởi tạo thành công! desu~!");
  console.log("📂 Python Core đang nằm tại:", path.join(rootDir, 'taxsentry-core'));
  console.log("\n📋 Các lệnh sắp có (Phase 2-4):");
  console.log("  • taxsentry setup       : Chạy wizard cấu hình ban đầu");
  console.log("  • taxsentry start       : Khởi chạy TUI Dashboard + Automation");
  console.log("  • taxsentry bot         : Khởi chạy Telegram Bot background");
  console.log("  • taxsentry status      : Kiểm tra trạng thái hệ thống");
  console.log("  • taxsentry stop        : Dừng các tiến trình nền");
  console.log("\n✨ Sếp Thiên Ân ơi, Phase 1 hoàn thành rực rỡ! Chúng ta sẽ sớm triển khai Installer và Onboarding Wizard nha~! ♪ (◕‿◕)");
} else {
  console.log(`⚠️ Lệnh '${command}' chưa được triển khai trong Phase 1. Vui lòng chạy 'taxsentry' hoặc 'taxsentry start'.`);
}
