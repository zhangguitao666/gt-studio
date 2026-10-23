-- Guarded synthetic Alpha/Blend and lower-track experiment.
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
local m=resolve:GetProjectManager();local p=m:GetCurrentProject();assert(p and p:GetName()=='REA Reference · 2026-10-21');assert(not p:IsRenderingInProgress())
local t=p:GetCurrentTimeline();assert(t:GetName():find('REA_AUDIO_BOUNDARY_',1,true)==1)
local row={after={audio_format_probe=true,formats=p:GetRenderFormats(),codecs={},current=p:GetCurrentRenderFormatAndCodec()},timeline=t:GetName(),completed=true}
for k,v in pairs(row.after.formats or {}) do
 if (tostring(k)..tostring(v)):lower():find('wav') or (tostring(k)..tostring(v)):lower():find('audio') then row.after.codecs[tostring(v)]=p:GetRenderCodecs(v) end
end
local before=p:GetCurrentRenderFormatAndCodec();row.after.attempts={}
for _,candidate in ipairs({'lpcm',''}) do
 local ok,value=pcall(function()return p:SetCurrentRenderFormatAndCodec('wav',candidate)end)
 row.after.attempts[#row.after.attempts+1]={codec=candidate,call_ok=ok,value=value,current=p:GetCurrentRenderFormatAndCodec()}
 assert(p:SetCurrentRenderFormatAndCodec(before.format,before.codec))
end
assert(t:AddMarker(4,'Cyan','REA_AUDIO_FORMAT_PROBE',json(row),1,json(row)));m:SaveProject();print('REA_AUDIO_FORMAT_PROBE='..json(row))
