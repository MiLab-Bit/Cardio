import React, { useEffect, useRef } from 'react'

function Starfield() {
  const layer1Ref = useRef(null)
  const layer2Ref = useRef(null)
  const layer3Ref = useRef(null)

  useEffect(() => {
    function createStars(container, count, sizeClass) {
      if (!container) return
      // Clear existing stars
      while (container.firstChild) {
        container.removeChild(container.firstChild)
      }
      for (let i = 0; i < count; i++) {
        const star = document.createElement('div')
        star.className = `star ${sizeClass}`
        star.style.left = `${Math.random() * 100}%`
        star.style.top = `${Math.random() * 100}%`
        if (sizeClass === 'large') {
          star.style.animationDelay = `${Math.random() * 3}s`
        }
        container.appendChild(star)
      }
    }

    createStars(layer1Ref.current, 180, 'small')
    createStars(layer2Ref.current, 100, 'medium')
    createStars(layer3Ref.current, 50, 'large')
  }, [])

  return (
    <div className="starfield">
      <div className="nebula nebula-1" />
      <div className="nebula nebula-2" />
      <div className="nebula nebula-3" />
      <div ref={layer1Ref} />
      <div ref={layer2Ref} />
      <div ref={layer3Ref} />
    </div>
  )
}

export default Starfield
