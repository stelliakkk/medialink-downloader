const gallery = document.querySelector('[data-gallery]')
const tabs = [...gallery.querySelectorAll('.gallery-nav a')]
const panels = tabs.map(tab => document.querySelector(tab.hash))
const tablist = gallery.querySelector('.gallery-nav')
const stacked = matchMedia('(max-width: 43rem)')

function activateTab(index, moveFocus = false) {
  tabs.forEach((tab, position) => {
    const selected = position === index
    tab.setAttribute('aria-selected', String(selected))
    tab.tabIndex = selected ? 0 : -1
    panels[position].hidden = !selected
  })
  if (moveFocus) tabs[index].focus()
}

tablist.setAttribute('role', 'tablist')
function setTabOrientation() {
  tablist.setAttribute('aria-orientation', stacked.matches ? 'horizontal' : 'vertical')
}
setTabOrientation()
stacked.addEventListener('change', setTabOrientation)

tabs.forEach((tab, index) => {
  const panel = panels[index]
  tab.setAttribute('role', 'tab')
  tab.setAttribute('aria-controls', panel.id)
  panel.setAttribute('role', 'tabpanel')
  panel.setAttribute('aria-labelledby', tab.id)
  panel.tabIndex = 0
  tab.addEventListener('click', event => {
    event.preventDefault()
    activateTab(index)
  })
  tab.addEventListener('keydown', event => {
    const forward = stacked.matches ? 'ArrowRight' : 'ArrowDown'
    const back = stacked.matches ? 'ArrowLeft' : 'ArrowUp'
    const destinations = {
      [forward]: (index + 1) % tabs.length,
      [back]: (index + tabs.length - 1) % tabs.length,
      Home: 0,
      End: tabs.length - 1,
      ' ': index,
    }
    if (!Object.hasOwn(destinations, event.key)) return
    event.preventDefault()
    activateTab(destinations[event.key], true)
  })
})

function selectLinkedPanel() {
  const index = tabs.findIndex(tab => tab.hash === location.hash)
  if (index >= 0) activateTab(index)
}
activateTab(0)
selectLinkedPanel()
addEventListener('hashchange', selectLinkedPanel)
gallery.dataset.enhanced = ''

const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)')
if (!reducedMotion.matches && 'IntersectionObserver' in window) {
  const reveal = new IntersectionObserver(entries => {
    for (const { target, isIntersecting } of entries) {
      if (!isIntersecting) continue
      target.classList.add('is-visible')
      reveal.unobserve(target)
    }
  })
  for (const item of document.querySelectorAll('[data-reveal]')) {
    if (item.getBoundingClientRect().top < innerHeight) continue
    item.classList.add('pending')
    reveal.observe(item)
  }
}

const header = document.querySelector('.site-header')
const navLinks = [...header.querySelectorAll('nav a')]
const sections = navLinks.map(link => document.querySelector(link.hash))
const stage = document.querySelector('.hero-depth')
const hero = document.querySelector('.hero')
const steps = document.querySelector('.steps')
const wide = matchMedia('(min-width: 53.001rem)')
let frame = 0

function updateScrollState() {
  frame = 0
  const y = scrollY
  const threshold = Math.max(header.offsetHeight + 12, innerHeight * .25)
  const atEnd = y > 0 && Math.ceil(y + innerHeight) >= document.documentElement.scrollHeight
  const active = atEnd
    ? sections.length - 1
    : sections.findLastIndex(section => section.getBoundingClientRect().top <= threshold)
  header.classList.toggle('is-scrolled', y > 12)
  navLinks.forEach((link, index) => {
    if (index === active) link.setAttribute('aria-current', 'location')
    else link.removeAttribute('aria-current')
  })
  const shift = !reducedMotion.matches && wide.matches ? Math.min(y, hero.offsetHeight) * .045 : 0
  stage.style.setProperty('--stage-y', `${shift}px`)
  const progress = (innerHeight * .95 - steps.getBoundingClientRect().top) / (innerHeight * .45)
  steps.style.setProperty('--progress', reducedMotion.matches ? 1 : Math.max(0, Math.min(1, progress)))
}

function requestScrollUpdate() {
  if (!frame) frame = requestAnimationFrame(updateScrollState)
}
addEventListener('scroll', requestScrollUpdate, { passive: true })
addEventListener('resize', requestScrollUpdate)
reducedMotion.addEventListener('change', requestScrollUpdate)
updateScrollState()
