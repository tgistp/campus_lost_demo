import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import ShapeGrid from './vendor/ShapeGrid';
import SpotlightCard from './vendor/SpotlightCard';
import './style.css';

const send = (type, rest={}) => window.parent.postMessage({isStreamlitMessage:true,type,...rest}, '*');
const navigate = action => send('streamlit:setComponentValue', {value:action,dataType:'json'});

function App() {
  const [ready,setReady]=useState(false);
  const [reduced,setReduced]=useState(window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(()=>{
    const listener=e=>{if(e.source===window.parent && e.data?.type==='streamlit:render') setReady(true)};
    window.addEventListener('message',listener);
    const mq=window.matchMedia('(prefers-reduced-motion: reduce)');
    const motion=()=>setReduced(mq.matches);
    mq.addEventListener('change',motion);
    send('streamlit:componentReady',{apiVersion:1});
    const resize=()=>send('streamlit:setFrameHeight',{height:Math.max(620,Math.min(980,window.screen.availHeight-100))});
    resize(); window.addEventListener('resize',resize);
    return ()=>{window.removeEventListener('message',listener);window.removeEventListener('resize',resize);mq.removeEventListener('change',motion)};
  },[]);
  return <main>
    <div className="background" aria-hidden="true"><ShapeGrid shape="square" cellSize={64} speed={.12}
      lineColor="#242c27" hoverColor="#1ed760" hoverFillColor="#1ed760" fillOpacity={.12}
      glow={.1} fade={.7} twinkle={0} paused={reduced} intro={!reduced} clickCascade={false}/></div>
    <header><span className="wordmark">PNU<span className="dot">.</span></span><span>부산대학교<br/>양산캠퍼스 분실물</span></header>
    <section aria-label="시작하기">
      <div className="actions">
        <SpotlightCard className="action lost" spotlightColor="#1ed760" intensity={.11} borderGlow={.4} ambient={false}>
          <button disabled={!ready} onClick={()=>navigate('lost')}>
            <span className="eyebrow">물건을 잃어버렸다면</span>
            <span className="label">분실 신고</span>
            <span className="arrow" aria-hidden="true">↗</span>
          </button>
        </SpotlightCard>
        <SpotlightCard className="action found" spotlightColor="#1ed760" intensity={.09} borderGlow={.4}>
          <button disabled={!ready} onClick={()=>navigate('found')}>
            <span className="eyebrow">물건을 주웠다면</span>
            <span className="label">주운 물건 등록</span>
            <span className="arrow" aria-hidden="true">↗</span>
          </button>
        </SpotlightCard>
      </div>
    </section>
    <footer>LOST &amp; FOUND</footer>
  </main>;
}
createRoot(document.getElementById('root')).render(<App/>);
