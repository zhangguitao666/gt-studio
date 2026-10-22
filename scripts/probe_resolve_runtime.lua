-- Read-only Resolve Console probe. Execute with:
-- dofile('/Users/zgt/agent/resolve-reconstruction/scripts/probe_resolve_runtime.lua')
-- Only writes the explicitly selected evidence JSON; does not change Resolve state.
local OUTPUT = '/Users/zgt/agent/resolve-reconstruction/research/evidence/resolve-runtime-api.json'
local EXPECTED_PROJECT = 'REA Reference · 2026-10-21'
local STUB = '/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/DaVinciResolveScript.pyi'

local function quote(text)
    local replacements = {['"']='\\"', ['\\']='\\\\', ['\b']='\\b', ['\f']='\\f', ['\n']='\\n', ['\r']='\\r', ['\t']='\\t'}
    return '"' .. tostring(text):gsub('[%z\1-\31\\"]', function(c)
        return replacements[c] or string.format('\\u%04x', string.byte(c))
    end) .. '"'
end

local function encode(value, seen, depth)
    local kind = type(value)
    if kind == 'nil' then return 'null' end
    if kind == 'boolean' then return value and 'true' or 'false' end
    if kind == 'string' then return quote(value) end
    if kind == 'number' then
        if value ~= value or value == math.huge or value == -math.huge then
            return '{"__unsupported_number":' .. quote(tostring(value)) .. '}'
        end
        return tostring(value)
    end
    if kind ~= 'table' then return '{"__unsupported_type":' .. quote(kind) .. '}' end
    if seen[value] then return '{"__cycle":true}' end
    if depth > 40 then return '{"__depth_limit":40}' end
    seen[value] = true
    local count, maximum, array = 0, 0, true
    for key, _ in pairs(value) do
        count = count + 1
        if type(key) ~= 'number' or key < 1 or key ~= math.floor(key) then
            array = false
        else
            maximum = math.max(maximum, key)
        end
    end
    array = array and count == maximum and count > 0
    local parts = {}
    if array then
        for i=1,maximum do parts[#parts+1] = encode(value[i], seen, depth+1) end
    else
        local keys, all_strings = {}, true
        for key, _ in pairs(value) do
            keys[#keys+1] = key
            if type(key) ~= 'string' then all_strings = false end
        end
        if all_strings then
            table.sort(keys)
            for _,key in ipairs(keys) do parts[#parts+1] = quote(key) .. ':' .. encode(value[key], seen, depth+1) end
        else
            -- Avoid collisions/loss when a sparse or mixed-key table is not a JSON object.
            for _,key in ipairs(keys) do
                parts[#parts+1] = '{"key":' .. encode(key, seen, depth+1) .. ',"value":' .. encode(value[key], seen, depth+1) .. '}'
            end
            seen[value] = nil
            return '{"__table_entries":[' .. table.concat(parts, ',') .. ']}'
        end
    end
    seen[value] = nil
    if array then return '[' .. table.concat(parts, ',') .. ']' end
    return '{' .. table.concat(parts, ',') .. '}'
end

local report = {
    schema_version=1,
    probe='resolve-console-read-only-v1',
    captured_at_utc=os.date('!%Y-%m-%dT%H:%M:%SZ'),
    target='/Applications/DaVinci Resolve/DaVinci Resolve.app',
    invocation_context='Existing Resolve Lua Console; colon-method invocation',
    scope='Read-only inspection of application and the named dedicated scratch project.',
    expected_project=EXPECTED_PROJECT,
    declaration_source=STUB,
    queries={},
    limitations={
        'Only recorded successful calls establish runtime availability for their exact arguments and context.',
        'Reported render format/codec names do not prove encoding success, quality, option coverage or full feature parity.',
        'Empty Lua tables encode as JSON objects; explicit table_entry_count disambiguates empty results.',
        'Object handles use unsupported-type sentinels; handle acquisition is not feature validation.',
        'No mutation, rendering, import, preference change, page switch or Fusion registry query is performed.',
    },
}

local function probe(label, method, source_line, fn, arguments)
    local ok, value = pcall(fn)
    local record = {label=label, method=method, arguments=arguments or {},
        declaration={path=STUB,line=source_line}, success=ok,
        lua_return_type=ok and type(value) or nil}
    if ok then
        record.value = value
        if value == nil then record.returned_nil=true end
        if type(value) == 'table' then
            local n=0
            for _,_ in pairs(value) do n=n+1 end
            record.table_entry_count=n
        end
    else
        record.error=tostring(value)
    end
    report.queries[#report.queries+1]=record
    if ok then return value, true end
    return nil, false
end

local r = rawget(_G, 'resolve')
if r == nil then
    report.fatal_error='No resolve global exists in this Console; no scriptapp fallback attempted.'
else
    probe('version_string','Resolve.GetVersionString',1589,function() return r:GetVersionString() end)
    probe('version_fields','Resolve.GetVersion',1586,function() return r:GetVersion() end)
    probe('product_name','Resolve.GetProductName',1592,function() return r:GetProductName() end)
    probe('is_studio','Resolve.IsStudio',1595,function() return r:IsStudio() end)
    probe('current_page','Resolve.GetCurrentPage',1580,function() return r:GetCurrentPage() end)
    local manager=probe('project_manager_handle','Resolve.GetProjectManager',1556,function() return r:GetProjectManager() end)
    local project=probe('current_project_handle','ProjectManager.GetCurrentProject',1709,function()
        if manager==nil then error('Project manager unavailable') end
        return manager:GetCurrentProject()
    end)
    local name=probe('project_name','Project.GetName',1799,function()
        if project==nil then error('No current project') end
        return project:GetName()
    end)
    report.scratch_project_identity_matches = name == EXPECTED_PROJECT
    if name == EXPECTED_PROJECT then
        probe('project_unique_id','Project.GetUniqueId',1916,function() return project:GetUniqueId() end)
        probe('project_settings','Project.GetSettings',1871,function() return project:GetSettings() end)
        probe('timeline_count','Project.GetTimelineCount',1790,function() return project:GetTimelineCount() end)
        local timeline=probe('current_timeline_handle','Project.GetCurrentTimeline',1784,function() return project:GetCurrentTimeline() end)
        if timeline~=nil then
            probe('current_timeline_name','Timeline.GetName',2186,function() return timeline:GetName() end)
        end
        probe('render_queue','Project.GetRenderJobList',1826,function() return project:GetRenderJobList() end)
        probe('rendering_in_progress','Project.IsRenderingInProgress',1853,function() return project:IsRenderingInProgress() end)
        probe('current_render_format_codec','Project.GetCurrentRenderFormatAndCodec',1901,function() return project:GetCurrentRenderFormatAndCodec() end)
        probe('current_render_mode','Project.GetCurrentRenderMode',1907,function() return project:GetCurrentRenderMode() end)
        local formats=probe('render_formats','Project.GetRenderFormats',1889,function() return project:GetRenderFormats() end)
        local audio_formats=probe('audio_render_formats','Project.GetAudioRenderFormats',1892,function() return project:GetAudioRenderFormats() end)
        local function inspect_codecs(format_table, audio)
            if type(format_table)~='table' then return end
            local seen={}
            for _,extension in pairs(format_table) do
                if type(extension)=='string' and not seen[extension] then
                    seen[extension]=true
                    local ext=extension
                    if audio then
                        probe('audio_codecs:'..ext,'Project.GetAudioRenderCodecs',1898,function() return project:GetAudioRenderCodecs(ext) end,{extension=ext})
                    else
                        probe('render_codecs:'..ext,'Project.GetRenderCodecs',1895,function() return project:GetRenderCodecs(ext) end,{extension=ext})
                    end
                end
            end
        end
        inspect_codecs(formats,false)
        inspect_codecs(audio_formats,true)
        local pool=probe('media_pool_handle','Project.GetMediaPool',1781,function() return project:GetMediaPool() end)
        local root=probe('media_pool_root_handle','MediaPool.GetRootFolder',1976,function()
            if pool==nil then error('Media pool unavailable') end
            return pool:GetRootFolder()
        end)
        if root~=nil then
            probe('media_pool_root_name','Folder.GetName',2681,function() return root:GetName() end)
            probe('media_pool_root_clips','Folder.GetClipList',2687,function() return root:GetClipList() end)
            probe('media_pool_root_subfolders','Folder.GetSubFolderList',2684,function() return root:GetSubFolderList() end)
        end
    else
        report.project_queries_skipped='Current project does not match dedicated scratch project; no project settings/media enumeration performed.'
    end
end

-- Preserve full results even when Resolve's safe scripting environment omits io.
report.persistence = {output=OUTPUT, io_available=type(io)=='table' and type(io.open)=='function'}
report.persistence.status = report.persistence.io_available and 'pending' or 'io_unavailable_safe_scripting'
REA_RUNTIME_REPORT = report

local function safe_encode(value)
    local ok, payload=pcall(function() return encode(value, {}, 0) end)
    if ok then return payload end
    return '{"schema_version":1,"fatal_error":'..quote('JSON encoding failed: '..tostring(payload))..'}'
end

local function compact(value, limit, depth)
    if type(value)=='string' then
        if #value > 180 then return {text_prefix=value:sub(1,180), omitted_bytes=#value-180} end
        return value
    end
    if type(value)=='number' or type(value)=='boolean' or value==nil then return value end
    if type(value)~='table' then return {unsupported_type=type(value)} end
    local keys={}
    for key,_ in pairs(value) do keys[#keys+1]=key end
    table.sort(keys,function(a,b) return tostring(a)<tostring(b) end)
    if depth>=2 then return {table_entry_count=#keys, omitted_entries=#keys} end
    local entries={}
    for index,key in ipairs(keys) do
        if index>limit then break end
        entries[#entries+1]={key=compact(key,limit,depth+1),value=compact(value[key],limit,depth+1)}
    end
    return {table_entry_count=#keys, entries=entries, omitted_entries=math.max(0,#keys-limit)}
end

local function build_summary(limit)
    local summary={schema_version=1,probe=report.probe,captured_at_utc=report.captured_at_utc,
        scratch_project_identity_matches=report.scratch_project_identity_matches,
        fatal_error=report.fatal_error, project_queries_skipped=report.project_queries_skipped,
        persistence=report.persistence, query_count=#report.queries, queries={},
        limitations={'Compact capture; omitted entries are explicit. Full results remain in REA_RUNTIME_REPORT and REA_RUNTIME_PAYLOAD.'}}
    for _,query in ipairs(report.queries) do
        summary.queries[#summary.queries+1]={label=query.label,method=query.method,success=query.success,
            returned_nil=query.returned_nil,value=compact(query.value,limit,0),
            error=query.error and query.error:sub(1,180) or nil}
    end
    return summary
end

REA_RUNTIME_PAYLOAD=safe_encode(report)
if report.persistence.io_available then
    local ok,reason=pcall(function()
        local file,open_error=io.open(OUTPUT,'w')
        if not file then error(tostring(open_error)) end
        report.persistence.status='written'
        REA_RUNTIME_PAYLOAD=safe_encode(report)
        local written,write_error=file:write(REA_RUNTIME_PAYLOAD,'\n')
        file:close()
        if not written then error(tostring(write_error)) end
    end)
    if not ok then
        report.persistence.status='write_failed'
        report.persistence.error=tostring(reason)
        REA_RUNTIME_PAYLOAD=safe_encode(report)
    end
end

local summary,payload
for _,limit in ipairs({6,3,1,0}) do
    summary=build_summary(limit)
    payload=safe_encode(summary)
    if #payload<=7800 then break end
end
-- Keep a bounded capture even for unexpected large codec lists; omissions are counted.
while #payload>7800 and #summary.queries>0 do
    table.remove(summary.queries)
    summary.omitted_query_records=summary.query_count-#summary.queries
    payload=safe_encode(summary)
end
REA_RUNTIME_SUMMARY=summary
REA_RUNTIME_SUMMARY_PAYLOAD=payload
function REA_RUNTIME_PRINT_CHUNK(first,count)
    first=tonumber(first) or 1
    count=math.min(tonumber(count) or 2048,4096)
    print('REA_RUNTIME_CHUNK['..tostring(first)..']='..REA_RUNTIME_PAYLOAD:sub(first,first+count-1))
end
print('REA_RUNTIME_PAYLOAD_BYTES='..tostring(#REA_RUNTIME_PAYLOAD)..'; persistence='..report.persistence.status)
print('REA_RUNTIME_SUMMARY='..payload)
