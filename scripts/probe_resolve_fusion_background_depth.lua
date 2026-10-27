-- Controlled generator precision probe; new synthetic timelines only.
local function quote(s)
 return '"'..tostring(s):gsub('[%z\1-\31\\"]',function(c)
  return ({['"']='\\"',['\\']='\\\\',['\n']='\\n',['\r']='\\r',['\t']='\\t'})[c] or string.format('\\u%04x',string.byte(c))
 end)..'"'
end
local function json(x)
 local t=type(x)
 if t=='nil' then return 'null' end
 if t=='string' then return quote(x) end
 if t=='boolean' or t=='number' then return tostring(x) end
 if t~='table' then return quote('<'..t..'>') end
 local keys={};for k,_ in pairs(x) do keys[#keys+1]=k end
 local array=#keys>0
 for _,k in ipairs(keys) do if type(k)~='number' then array=false end end
 local out={}
 if array then for i=1,#x do out[#out+1]=json(x[i]) end;return '['..table.concat(out,',')..']' end
 table.sort(keys,function(a,b)return tostring(a)<tostring(b)end)
 for _,k in ipairs(keys) do out[#out+1]=quote(k)..':'..json(x[k]) end
 return '{'..table.concat(out,',')..'}'
end

local m=resolve:GetProjectManager();local p=m:GetCurrentProject();assert(p and p:GetName()=='REA Reference · 2026-10-21','Wrong reference project');assert(not p:IsRenderingInProgress(),'Reference render active')
local root='/Users/zgt/agent/resolve-reconstruction/workspace/fusion-background-depth';local pool=p:GetMediaPool();local imported=pool:ImportMedia({'/Users/zgt/agent/resolve-reconstruction/workspace/fusion-concat-native-v2/source320.mov'});assert(imported and imported[1])
local codec='FFV1IntraRGBA_16';local found=false;for _,v in pairs(p:GetRenderCodecs('mov') or {}) do if v==codec then found=true end end;assert(found and p:SetCurrentRenderFormatAndCodec('mov',codec));assert(p:SetCurrentRenderMode(1))
local prefix='REA_FUSION_DEPTH_'..os.date('%Y%m%d_%H%M%S')..'_';local ids={}
for depth=0,4 do
 local t=pool:CreateEmptyTimeline(prefix..depth);assert(t and p:SetCurrentTimeline(t));local row={after={fusion_background_depth=true,depth_requested=depth,version=resolve:GetVersionString(),nodes={},depth_preferences={}},timeline=t:GetName(),completed=false};local a=row.after
 local ok,err=pcall(function()
  assert(t:SetSetting('useCustomSettings','1'));assert(t:SetSetting('timelineResolutionWidth','320'));assert(t:SetSetting('timelineResolutionHeight','320'))
  local clips=pool:AppendToTimeline({{mediaPoolItem=imported[1],startFrame=0,endFrame=12,recordFrame=t:GetStartFrame(),trackIndex=1}});assert(clips and clips[1]);local clip=clips[1];local comp=clip:AddFusionComp();assert(comp);local out
  for _,n in pairs(comp:GetToolList(false)) do if n:GetAttrs().TOOLS_RegID=='MediaOut' then out=n end end
  local bg=comp:AddTool('Background');assert(bg and out)
  local inputs={UseFrameFormatSettings=0,Width=320,Height=320,TopLeftRed=.12345,TopLeftGreen=.375,TopLeftBlue=.54321,TopLeftAlpha=.12345,Depth=depth}
  for key,value in pairs(inputs) do assert(bg:SetInput(key,value)~=false);local v=bg:GetInput(key);assert(type(v)=='number' and math.abs(v-value)<1e-6,'Readback differs: '..key) end
  assert(out:ConnectInput('Input',bg)~=false);a.inputs={};for key,_ in pairs(inputs) do a.inputs[key]=bg:GetInput(key) end
  local seen={};local count=0
  local function scan(value,path,level)
   if type(value)~='table' or seen[value] or level>12 then return end;seen[value]=true
   for key,v in pairs(value) do count=count+1;if count>2000 then return end;local name=path..'.'..tostring(key)
    if type(v)=='table' then scan(v,name,level+1) elseif name:lower():find('depth',1,true) and (type(v)=='number' or type(v)=='string' or type(v)=='boolean') then a.depth_preferences[name]=v end
   end
  end
  local good,prefs=pcall(function()return comp:GetPrefs()end);a.preferences_read_ok=good;if good then scan(prefs,'Comp',0) end
  a.clip_duration=clip:GetDuration(true);a.timeline_settings={width=t:GetSetting('timelineResolutionWidth'),height=t:GetSetting('timelineResolutionHeight'),fps=t:GetSetting('timelineFrameRate')}
  local settings={SelectAllFrames=true,TargetDir=root,CustomName=t:GetName(),ExportVideo=true,ExportAudio=false,FormatWidth=320,FormatHeight=320,FrameRate=24,ExportAlpha=true,AlphaMode=1,ExportSubtitle=false}
  assert(p:SetRenderSettings(settings));local id=p:AddRenderJob();assert(id and id~='');a.job_id=id;a.settings=settings;ids[#ids+1]=id;row.completed=true
 end)
 if not ok then a.error=tostring(err) end
 assert(t:AddMarker(0,ok and 'Green' or 'Red','REA_FUSION_BACKGROUND_DEPTH',json(row),1,json(row)));m:SaveProject()
end
if #ids>0 then local started=p:StartRendering(ids,false);local t=p:GetCurrentTimeline();local row={after={fusion_background_depth_launch=true,ids=ids,started=started},timeline=t:GetName(),completed=true};assert(t:AddMarker(1,'Blue','REA_FUSION_BACKGROUND_DEPTH_LAUNCH',json(row),1,json(row)));m:SaveProject() end
resolve:OpenPage('edit')
