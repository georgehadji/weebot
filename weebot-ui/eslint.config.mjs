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
