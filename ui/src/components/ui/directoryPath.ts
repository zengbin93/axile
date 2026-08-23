export interface DirectoryCrumb {
  label: string
  path: string
}

/** 将后端绝对路径拆成可点击面包屑，同时支持 Windows 与 POSIX. */
export function directoryBreadcrumbs(path: string): DirectoryCrumb[] {
  const windows = /^([A-Za-z]:)[\\/]/.exec(path)
  if (windows) {
    const drive = windows[1]
    const parts = path.slice(windows[0].length).split(/[\\/]+/).filter(Boolean)
    const crumbs: DirectoryCrumb[] = [{ label: drive, path: `${drive}\\` }]
    let current = `${drive}\\`
    for (const part of parts) {
      current += `${part}\\`
      crumbs.push({ label: part, path: current })
    }
    return crumbs
  }

  const parts = path.split('/').filter(Boolean)
  const crumbs: DirectoryCrumb[] = [{ label: '/', path: '/' }]
  let current = ''
  for (const part of parts) {
    current += `/${part}`
    crumbs.push({ label: part, path: current })
  }
  return crumbs
}
