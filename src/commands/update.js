import chalk from 'chalk';

import { loadConfig, saveConfig, writeEnvFile } from '../config.js';

export default async function updateCommand() {
  const config = loadConfig();
  saveConfig(config);
  writeEnvFile(config);
  console.log(chalk.green('Runtime config refreshed. Re-run setup if you want to change provider/model.'));
}
