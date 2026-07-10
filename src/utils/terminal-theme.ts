import boxen from 'boxen';
import chalk from 'chalk';

export const BLUE_THEME = {
  primary: chalk.hex('#38bdf8'),
  secondary: chalk.hex('#0ea5e9'),
  accent: chalk.hex('#67e8f9'),
  muted: chalk.hex('#94a3b8'),
  success: chalk.hex('#22d3ee'),
  warn: chalk.hex('#93c5fd'),
  danger: chalk.hex('#fb7185'),
};

export function oceanFrame(title, lines, { borderColor = 'blue', subtitle = '', footer = '' } = {}) {
  const body = [];
  if (title) body.push(chalk.bold.hex('#38bdf8')(title));
  if (subtitle) body.push(chalk.dim(subtitle));
  if (subtitle) body.push('');
  body.push(...lines);
  if (footer) {
    body.push('');
    body.push(chalk.dim(footer));
  }
  return boxen(body.join('\n'), {
    padding: 1,
    margin: { top: 0, bottom: 1 },
    borderStyle: 'round',
    borderColor,
    title: 'TaxSentry',
    titleAlignment: 'center',
  });
}

