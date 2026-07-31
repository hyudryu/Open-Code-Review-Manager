## Summary

Remove the model dropdown from the Providers widget on the Overview page. The section now only shows each provider's status with a simple green/yellow/grey dot.

## Changes

- [frontend/src/pages/OverviewPage.tsx] Remove the model selection `<select>` from `ProviderRow` component
- [frontend/src/pages/OverviewPage.tsx] Simplify `ProviderRow` to only display provider name, protocol, base URL, and status indicator
- [frontend/src/pages/OverviewPage.tsx] Remove unused imports (`useModels`, `useUpdateProfile`, `useProfiles`, `ReviewProfile` type)

## Tests

- [ ] Backend tests pass (`pytest`)
- [x] TypeScript compiles (`npx tsc --noEmit`)
- [ ] Manually verified

## Notes

Model selection is still available on the full Providers management page (`/providers`). This only simplifies the Overview widget.
