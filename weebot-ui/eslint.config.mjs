import { defineConfig, globalIgnores } from 'eslint/config';
import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTs from 'eslint-config-next/typescript';

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores(['.next/**', '.next-e2e/**', 'out/**', 'build/**', 'next-env.d.ts', 'test-results/**', 'playwright-report/**']),

  // Layer rules (tasks/specs/ui_ux_remediation_plan.md, Phase 0.5): dependencies point down only.
  // Primitives know nothing about Weebot; lib/ is pure (no React).
  {
    files: ['src/components/ui/**/*.{ts,tsx}'],
    ignores: ['**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/hooks/*', '@/providers/*', '@/lib/*', '!@/lib/utils'],
              message: 'components/ui is Weebot-agnostic: it may import only @/lib/utils.',
            },
          ],
        },
      ],
    },
  },
  // Regression guards for the 2026-11-03 Web Interface Guidelines audit
  // (tasks/plans/web_guidelines_audit_2026_11_03_fix_plan.md, Phase 10). Add only; never loosen.
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['**/*.test.{ts,tsx}', 'src/lib/format.ts', 'src/lib/storage.ts'],
    rules: {
      'no-restricted-syntax': [
        'error',
        { selector: 'JSXText[value=/[.][.][.]/]', message: 'Use the ellipsis character "…", not three dots.' },
        { selector: 'Literal[value=/transition-all/]', message: 'List the properties: transition-colors, transition-[opacity,transform], ...' },
        { selector: 'TemplateElement[value.raw=/transition-all/]', message: 'List the properties: transition-colors, transition-[opacity,transform], ...' },
        { selector: "CallExpression[callee.property.name='toFixed']", message: 'Format numbers through lib/format.ts (Intl).' },
        { selector: "CallExpression[callee.property.name='toLocaleString']", message: 'Format through lib/format.ts so the locale and time zone are explicit.' },
        { selector: "Identifier[name=/^(localStorage|sessionStorage)$/]", message: 'Use lib/storage.ts (never throws, notifies subscribers).' },
      ],
    },
  },
  {
    files: ['src/lib/**/*.{ts,tsx}'],
    ignores: ['**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        { paths: [{ name: 'react', message: 'lib/ is pure: React belongs in hooks/.' }, { name: 'react-dom' }] },
      ],
    },
  },
]);
